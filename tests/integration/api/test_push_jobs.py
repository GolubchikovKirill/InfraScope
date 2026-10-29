from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlmodel import select

from app.api.routes import remote_access_push
from app.core.config import settings
from app.domains.remote_access import push_jobs, service, winrm_exec
from app.domains.remote_access.models import RemoteAccessDevice, RemoteAccessPushJob


@pytest.fixture(autouse=True)
def _winrm_configured(monkeypatch):
    monkeypatch.setattr(settings, "WINRM_ADMIN_USERNAME", "svc-infrascope")
    monkeypatch.setattr(settings, "WINRM_ADMIN_PASSWORD", "winrm-secret-for-tests")


@pytest.fixture(autouse=True)
def _no_real_dispatch(monkeypatch):
    """The route dispatches a Celery task right after queueing; stub it out so
    these tests never touch a broker (same pattern as test_ml.py)."""
    enqueued: list[str] = []
    monkeypatch.setattr(
        remote_access_push,
        "remote_access_push_job_task",
        SimpleNamespace(apply_async=lambda args, **_kw: enqueued.append(args[0])),
    )
    return enqueued


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _device(db_session, hostname: str, **over) -> RemoteAccessDevice:
    dev = service.ensure_device(db_session, hostname=hostname, permanent_password="pw-" + hostname)
    for key, value in over.items():
        setattr(dev, key, value)
    db_session.add(dev)
    db_session.commit()
    db_session.refresh(dev)
    return dev


def _enqueue(client, admin_token, devices, **body):
    return client.post("/api/v1/remote-access/push", json={"device_ids": [str(d.id) for d in devices], **body}, headers=_auth(admin_token))


# --------------------------------------------------------------------------- #
# queueing                                                                    #
# --------------------------------------------------------------------------- #
def test_queueing_a_push_requires_a_superuser(client, user_token, db_session):
    dev = _device(db_session, "VNA-KKM-701")

    assert client.post("/api/v1/remote-access/push", json={"device_ids": [str(dev.id)]}).status_code == 401
    assert client.post("/api/v1/remote-access/push", json={"device_ids": [str(dev.id)]}, headers=_auth(user_token)).status_code == 403
    assert client.get("/api/v1/remote-access/push/jobs", headers=_auth(user_token)).status_code == 403


def test_queueing_is_503_when_winrm_is_not_configured(client, admin_token, db_session, monkeypatch):
    monkeypatch.setattr(settings, "WINRM_ADMIN_USERNAME", "")
    dev = _device(db_session, "VNA-KKM-701")

    response = _enqueue(client, admin_token, [dev])

    assert response.status_code == 503
    assert db_session.exec(select(RemoteAccessPushJob)).all() == []


def test_queueing_creates_a_waiting_job_per_device_and_dispatches_it(client, admin_token, db_session, _no_real_dispatch):
    till = _device(db_session, "VNA-KKM-701")
    engineer = _device(db_session, "VNK-ITD-SA04", deploy_profile="admin")

    body = _enqueue(client, admin_token, [till, engineer]).json()

    assert {(j["hostname"], j["profile"], j["state"]) for j in body["queued"]} == {
        ("VNA-KKM-701", "client", "queued"),
        ("VNK-ITD-SA04", "admin", "queued"),
    }
    assert body["skipped"] == []
    assert all(j["requested_by"] for j in body["queued"])
    assert "runner" not in body["queued"][0]
    assert sorted(_no_real_dispatch) == sorted(j["id"] for j in body["queued"])


def test_an_explicit_profile_overrides_the_devices_own(client, admin_token, db_session):
    dev = _device(db_session, "VNA-KKM-701")

    job = _enqueue(client, admin_token, [dev], profile="admin", dry_run=True).json()["queued"][0]

    assert job["profile"] == "admin" and job["dry_run"] is True


def test_devices_that_must_not_be_pushed_are_skipped_with_a_reason(client, admin_token, db_session):
    removed = _device(db_session, "VNA-KKM-702", managed=False)
    xp = _device(db_session, "VNA-KKM-703", os_caption="Microsoft Windows XP Professional")
    ok = _device(db_session, "VNA-KKM-704")

    first = _enqueue(client, admin_token, [removed, xp, ok]).json()
    again = _enqueue(client, admin_token, [ok]).json()

    assert [j["hostname"] for j in first["queued"]] == ["VNA-KKM-704"]
    assert {s["hostname"]: s["reason"] for s in first["skipped"]} == {
        "VNA-KKM-702": "не в управлении",
        "VNA-KKM-703": "Windows XP: RustDesk там не работает",
    }
    assert again["queued"] == [] and again["skipped"][0]["reason"] == "уже в очереди или выполняется"


def test_an_unknown_device_is_a_404_and_nothing_is_queued(client, admin_token, db_session):
    dev = _device(db_session, "VNA-KKM-701")
    missing = "00000000-0000-0000-0000-000000000001"

    response = client.post("/api/v1/remote-access/push", json={"device_ids": [str(dev.id), missing]}, headers=_auth(admin_token))

    assert response.status_code == 404
    assert db_session.exec(select(RemoteAccessPushJob)).all() == []


def test_a_waiting_job_can_be_cancelled_a_running_one_cannot(client, admin_token, db_session):
    a, b = _device(db_session, "VNA-KKM-701"), _device(db_session, "VNA-KKM-702")
    jobs = _enqueue(client, admin_token, [a, b]).json()["queued"]
    running_id = jobs[0]["id"]
    running = db_session.get(RemoteAccessPushJob, uuid.UUID(running_id))
    running.state = "running"
    db_session.add(running)
    db_session.commit()
    waiting = jobs[1]

    assert client.post(f"/api/v1/remote-access/push/jobs/{waiting['id']}/cancel", headers=_auth(admin_token)).status_code == 200
    assert client.post(f"/api/v1/remote-access/push/jobs/{running_id}/cancel", headers=_auth(admin_token)).status_code == 409


def test_jobs_listing_reports_whether_winrm_is_configured(client, admin_token, monkeypatch):
    monkeypatch.setattr(settings, "WINRM_ADMIN_USERNAME", "")

    assert client.get("/api/v1/remote-access/push/jobs", headers=_auth(admin_token)).json()["configured"] is False


# --------------------------------------------------------------------------- #
# execute_push_job - the Celery task body, run directly against fake WinRM    #
# --------------------------------------------------------------------------- #
def _queued_job(db_session, admin_token=None, client=None, hostname="VNA-KKM-701", **enqueue) -> tuple[RemoteAccessDevice, RemoteAccessPushJob]:
    dev = _device(db_session, hostname)
    job = RemoteAccessPushJob(device_id=dev.id, hostname=dev.hostname, profile=enqueue.get("profile", dev.deploy_profile), dry_run=enqueue.get("dry_run", False))
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return dev, job


def test_a_successful_push_marks_the_job_done_but_leaves_device_state_to_the_self_report(db_session, monkeypatch):
    dev, job = _queued_job(db_session)
    monkeypatch.setattr(winrm_exec, "run_powershell", lambda *_a, **_kw: winrm_exec.WinRMResult(ok=True, exit_code=0, stdout="DONE", stderr="", detail="DONE"))

    result = push_jobs.execute_push_job(db_session, job)

    assert result.state == "succeeded" and result.finished_at is not None and result.detail == "DONE"
    # only the device's own /deploy/report call moves deploy_state - a push job
    # succeeding only means the trigger ran to completion, see push_jobs.py
    db_session.expire_all()
    assert db_session.get(RemoteAccessDevice, dev.id).deploy_state == "pending"


def test_a_failed_push_fails_the_job_with_the_detail(db_session, monkeypatch):
    _dev, job = _queued_job(db_session)
    monkeypatch.setattr(winrm_exec, "run_powershell", lambda *_a, **_kw: winrm_exec.WinRMResult(ok=False, exit_code=1, stdout="", stderr="Access is denied", detail="Access is denied"))

    result = push_jobs.execute_push_job(db_session, job)

    assert result.state == "failed" and result.detail == "Access is denied"


def test_winrm_not_configured_fails_the_job_without_raising(db_session, monkeypatch):
    _dev, job = _queued_job(db_session)

    def _boom(*_a, **_kw):
        raise winrm_exec.WinRMNotConfiguredError("WINRM_ADMIN_USERNAME / WINRM_ADMIN_PASSWORD are not set")

    monkeypatch.setattr(winrm_exec, "run_powershell", _boom)

    result = push_jobs.execute_push_job(db_session, job)

    assert result.state == "failed" and "WINRM_ADMIN_USERNAME" in (result.detail or "")


def test_a_dry_run_probes_instead_of_installing_and_never_touches_device_state(db_session, monkeypatch):
    dev, job = _queued_job(db_session, dry_run=True)
    probed = []
    monkeypatch.setattr(winrm_exec, "probe", lambda hostname: probed.append(hostname) or winrm_exec.WinRMResult(ok=True, exit_code=0, stdout="Windows 10 Pro | RustDesk service: absent", stderr="", detail="Windows 10 Pro | RustDesk service: absent"))
    install_called = []
    monkeypatch.setattr(winrm_exec, "run_powershell", lambda *_a, **_kw: install_called.append(1))

    result = push_jobs.execute_push_job(db_session, job)

    assert probed == [dev.hostname] and install_called == []
    assert result.state == "succeeded" and "RustDesk service: absent" in (result.detail or "")
    db_session.expire_all()
    assert db_session.get(RemoteAccessDevice, dev.id).deploy_state == "unknown"


def test_a_push_applies_the_jobs_profile_to_the_device_before_triggering(db_session, monkeypatch):
    dev = _device(db_session, "VNK-ITD-SA04")  # defaults to "client"
    job = RemoteAccessPushJob(device_id=dev.id, hostname=dev.hostname, profile="admin")
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    monkeypatch.setattr(winrm_exec, "run_powershell", lambda *_a, **_kw: winrm_exec.WinRMResult(ok=True, exit_code=0, stdout="DONE", stderr="", detail="DONE"))

    push_jobs.execute_push_job(db_session, job)

    db_session.expire_all()
    refreshed = db_session.get(RemoteAccessDevice, dev.id)
    assert refreshed.deploy_profile == "admin" and refreshed.desired_hidden is False


def test_a_machine_taken_out_of_management_after_queueing_is_skipped_not_pushed(db_session, monkeypatch):
    dev, job = _queued_job(db_session)
    dev.managed = False
    db_session.add(dev)
    db_session.commit()
    called = []
    monkeypatch.setattr(winrm_exec, "run_powershell", lambda *_a, **_kw: called.append(1))

    result = push_jobs.execute_push_job(db_session, job)

    assert result.state == "skipped" and called == []


def test_a_cancelled_job_is_left_alone(db_session, monkeypatch):
    _dev, job = _queued_job(db_session)
    job.state = "cancelled"
    db_session.add(job)
    db_session.commit()
    called = []
    monkeypatch.setattr(winrm_exec, "run_powershell", lambda *_a, **_kw: called.append(1))

    result = push_jobs.execute_push_job(db_session, job)

    assert result.state == "cancelled" and called == []


# --------------------------------------------------------------------------- #
# stale job reaping                                                           #
# --------------------------------------------------------------------------- #
def test_a_job_stuck_running_past_the_timeout_is_reaped_as_failed(db_session):
    _dev, job = _queued_job(db_session)
    job.state = "running"
    job.started_at = datetime.now(UTC) - timedelta(minutes=20)
    db_session.add(job)
    db_session.commit()

    reaped = push_jobs.reap_stale_push_jobs(db_session)

    assert reaped == 1
    db_session.expire_all()
    assert db_session.get(RemoteAccessPushJob, job.id).state == "failed"
