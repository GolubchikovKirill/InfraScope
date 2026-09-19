from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import select

from app.core.config import settings
from app.domains.remote_access import push_jobs, service
from app.domains.remote_access.models import RemoteAccessDevice, RemoteAccessPushJob

RUNNER_TOKEN = "runner-secret-for-tests"


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setattr(settings, "RUSTDESK_RUNNER_TOKEN", RUNNER_TOKEN)
    monkeypatch.setattr(settings, "RUSTDESK_DEPLOY_TOKEN", "")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


RUNNER = {"X-InfraScope-Runner-Token": RUNNER_TOKEN}


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
# operators                                                                   #
# --------------------------------------------------------------------------- #
def test_queueing_a_push_requires_a_superuser(client, user_token, db_session):
    dev = _device(db_session, "VNA-KKM-701")

    assert client.post("/api/v1/remote-access/push", json={"device_ids": [str(dev.id)]}).status_code == 401
    assert client.post("/api/v1/remote-access/push", json={"device_ids": [str(dev.id)]}, headers=_auth(user_token)).status_code == 403
    assert client.get("/api/v1/remote-access/push/jobs", headers=_auth(user_token)).status_code == 403


def test_queueing_creates_a_waiting_job_per_device_with_its_own_profile(client, admin_token, db_session):
    till = _device(db_session, "VNA-KKM-701")
    engineer = _device(db_session, "VNK-ITD-SA04", deploy_profile="admin")

    body = _enqueue(client, admin_token, [till, engineer]).json()

    assert {(j["hostname"], j["profile"], j["state"]) for j in body["queued"]} == {
        ("VNA-KKM-701", "client", "queued"),
        ("VNK-ITD-SA04", "admin", "queued"),
    }
    assert body["skipped"] == []
    assert all(j["requested_by"] for j in body["queued"])


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
    client.post("/api/v1/remote-access/runner/claim", json={"runner": "PC", "limit": 1}, headers=RUNNER)
    db_session.expire_all()
    running = next(j for j in db_session.exec(select(RemoteAccessPushJob)).all() if j.state == "running")
    waiting = next(j for j in jobs if str(j["id"]) != str(running.id))

    assert client.post(f"/api/v1/remote-access/push/jobs/{waiting['id']}/cancel", headers=_auth(admin_token)).status_code == 200
    assert client.post(f"/api/v1/remote-access/push/jobs/{running.id}/cancel", headers=_auth(admin_token)).status_code == 409


# --------------------------------------------------------------------------- #
# runner authentication                                                       #
# --------------------------------------------------------------------------- #
def test_the_runner_needs_the_token(client, db_session):
    body = {"runner": "PC"}

    assert client.post("/api/v1/remote-access/runner/claim", json=body).status_code == 401
    assert client.post("/api/v1/remote-access/runner/claim", json=body, headers={"X-InfraScope-Runner-Token": "nope"}).status_code == 401
    assert client.post("/api/v1/remote-access/runner/claim", json=body, headers=RUNNER).status_code == 200


def test_it_refuses_to_serve_anything_when_no_token_is_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "RUSTDESK_RUNNER_TOKEN", "")

    response = client.post("/api/v1/remote-access/runner/claim", json={"runner": "PC"}, headers=RUNNER)

    assert response.status_code == 503


def test_the_deploy_token_works_for_the_runner_when_there_is_no_runner_token(client, monkeypatch):
    monkeypatch.setattr(settings, "RUSTDESK_RUNNER_TOKEN", "")
    monkeypatch.setattr(settings, "RUSTDESK_DEPLOY_TOKEN", "the-deploy-token")

    ok = client.post("/api/v1/remote-access/runner/claim", json={"runner": "PC"}, headers={"X-InfraScope-Runner-Token": "the-deploy-token"})

    assert ok.status_code == 200


# --------------------------------------------------------------------------- #
# claim and report                                                            #
# --------------------------------------------------------------------------- #
def test_claiming_hands_out_the_oldest_jobs_with_this_machines_config(client, admin_token, db_session, monkeypatch):
    monkeypatch.setattr(settings, "RUSTDESK_ID_SERVER", "10.10.99.24")
    monkeypatch.setattr(settings, "RUSTDESK_KEY", "hbbs-public-key")
    a, b, c = (_device(db_session, h) for h in ("VNA-KKM-701", "VNA-KKM-702", "VNA-KKM-703"))
    _enqueue(client, admin_token, [a])
    _enqueue(client, admin_token, [b])
    _enqueue(client, admin_token, [c])

    jobs = client.post("/api/v1/remote-access/runner/claim", json={"runner": "ADMIN-PC", "limit": 2}, headers=RUNNER).json()["jobs"]

    assert [j["hostname"] for j in jobs] == ["VNA-KKM-701", "VNA-KKM-702"]
    first = jobs[0]["config"]
    # the machine gets the very password the address book holds for it
    assert first["permanent_password"] == "pw-VNA-KKM-701"
    assert first["rustdesk_id"] == "VNA_KKM_701"
    assert first["id_server"] == "10.10.99.24" and first["key"] == "hbbs-public-key"
    assert first["installer_msi"] == settings.RUSTDESK_INSTALLER_FILENAME
    states = {j.hostname: j.state for j in db_session.exec(select(RemoteAccessPushJob)).all()}
    assert states == {"VNA-KKM-701": "running", "VNA-KKM-702": "running", "VNA-KKM-703": "queued"}


def test_a_claimed_push_marks_the_device_as_being_rolled_out_but_a_dry_run_does_not(client, admin_token, db_session):
    real, probe = _device(db_session, "VNA-KKM-701"), _device(db_session, "VNA-KKM-702")
    _enqueue(client, admin_token, [real])
    _enqueue(client, admin_token, [probe], dry_run=True)

    client.post("/api/v1/remote-access/runner/claim", json={"runner": "PC", "limit": 5}, headers=RUNNER)

    db_session.expire_all()
    assert db_session.get(RemoteAccessDevice, real.id).deploy_state == "pending"
    assert db_session.get(RemoteAccessDevice, probe.id).deploy_state == "unknown"


def test_a_machine_taken_out_of_management_after_queueing_is_not_handed_out(client, admin_token, db_session):
    dev = _device(db_session, "VNA-KKM-701")
    _enqueue(client, admin_token, [dev])
    dev.managed = False
    db_session.add(dev)
    db_session.commit()

    jobs = client.post("/api/v1/remote-access/runner/claim", json={"runner": "PC"}, headers=RUNNER).json()["jobs"]

    assert jobs == []
    assert db_session.exec(select(RemoteAccessPushJob)).first().state == "skipped"


def _claim_one(client, admin_token, db_session, hostname="VNA-KKM-701", **enqueue):
    dev = _device(db_session, hostname)
    _enqueue(client, admin_token, [dev], **enqueue)
    job = client.post("/api/v1/remote-access/runner/claim", json={"runner": "PC"}, headers=RUNNER).json()["jobs"][0]
    return dev, uuid.UUID(job["id"])  # the tests read rows back by primary key


def _report(client, job_id, result, **extra):
    return client.post("/api/v1/remote-access/runner/report", json={"job_id": str(job_id), "result": result, **extra}, headers=RUNNER)


def test_a_successful_push_marks_the_job_done_and_the_device_configured(client, admin_token, db_session):
    dev, job_id = _claim_one(client, admin_token, db_session)

    assert _report(client, job_id, "ok", detail="RustDesk configured | service: Running/Auto", os_caption="Windows 10 Pro").status_code == 200

    db_session.expire_all()
    job = db_session.get(RemoteAccessPushJob, job_id)
    assert job.state == "succeeded" and job.finished_at is not None
    device = db_session.get(RemoteAccessDevice, dev.id)
    assert device.deploy_state == "configured" and device.os_caption == "Windows 10 Pro"


def test_a_warning_still_counts_as_configured_and_keeps_the_warning(client, admin_token, db_session):
    dev, job_id = _claim_one(client, admin_token, db_session)

    _report(client, job_id, "warn", detail="AppLocker step skipped")

    db_session.expire_all()
    assert db_session.get(RemoteAccessPushJob, job_id).detail == "предупреждение: AppLocker step skipped"
    assert db_session.get(RemoteAccessDevice, dev.id).deploy_state == "configured"


def test_a_failed_push_shows_on_the_device_with_the_reason(client, admin_token, db_session):
    dev, job_id = _claim_one(client, admin_token, db_session)

    _report(client, job_id, "failed", detail="Access is denied")

    db_session.expire_all()
    assert db_session.get(RemoteAccessPushJob, job_id).state == "failed"
    device = db_session.get(RemoteAccessDevice, dev.id)
    assert device.deploy_state == "failed" and device.deploy_detail == "Access is denied"


def test_a_skipped_machine_leaves_the_device_state_alone(client, admin_token, db_session):
    dev, job_id = _claim_one(client, admin_token, db_session)
    db_session.expire_all()
    state_before = db_session.get(RemoteAccessDevice, dev.id).deploy_state  # pending, set at claim

    _report(client, job_id, "skipped", detail="Windows XP: RustDesk is not supported")

    db_session.expire_all()
    assert db_session.get(RemoteAccessPushJob, job_id).state == "skipped"
    assert db_session.get(RemoteAccessDevice, dev.id).deploy_state == state_before


def test_a_dry_run_report_changes_nothing_on_the_device(client, admin_token, db_session):
    dev, job_id = _claim_one(client, admin_token, db_session, dry_run=True)

    _report(client, job_id, "dry_run", detail="RustDesk service: absent; would push profile 'client'")

    db_session.expire_all()
    assert db_session.get(RemoteAccessPushJob, job_id).state == "succeeded"
    assert db_session.get(RemoteAccessDevice, dev.id).deploy_state == "unknown"


def test_a_repeated_report_does_not_overwrite_the_first_verdict(client, admin_token, db_session):
    dev, job_id = _claim_one(client, admin_token, db_session)
    _report(client, job_id, "ok", detail="first")

    _report(client, job_id, "failed", detail="late duplicate")

    db_session.expire_all()
    assert db_session.get(RemoteAccessPushJob, job_id).state == "succeeded"
    assert db_session.get(RemoteAccessDevice, dev.id).deploy_state == "configured"


def test_a_report_for_an_unknown_job_is_a_404(client):
    assert _report(client, "00000000-0000-0000-0000-000000000009", "ok").status_code == 404


def test_a_report_needs_the_token(client, admin_token, db_session):
    _, job_id = _claim_one(client, admin_token, db_session)

    response = client.post("/api/v1/remote-access/runner/report", json={"job_id": str(job_id), "result": "ok"})

    assert response.status_code == 401


# --------------------------------------------------------------------------- #
# abandoned jobs and the runner heartbeat                                     #
# --------------------------------------------------------------------------- #
def test_a_job_abandoned_by_a_dead_runner_fails_and_says_so_on_the_device(client, admin_token, db_session):
    dev, job_id = _claim_one(client, admin_token, db_session)
    job = db_session.get(RemoteAccessPushJob, job_id)
    job.started_at = datetime.now(UTC) - push_jobs.RUNNING_JOB_TIMEOUT - timedelta(minutes=1)
    db_session.add(job)
    db_session.commit()

    body = client.get("/api/v1/remote-access/push/jobs", headers=_auth(admin_token)).json()

    assert body["data"][0]["state"] == "failed" and "не отчитался" in body["data"][0]["detail"]
    db_session.expire_all()
    assert db_session.get(RemoteAccessDevice, dev.id).deploy_state == "failed"


def test_a_running_job_within_the_timeout_is_left_alone(client, admin_token, db_session):
    _, job_id = _claim_one(client, admin_token, db_session)

    client.get("/api/v1/remote-access/push/jobs", headers=_auth(admin_token))

    db_session.expire_all()
    assert db_session.get(RemoteAccessPushJob, job_id).state == "running"


def test_the_queue_shows_whether_a_runner_is_connected(client, admin_token):
    before = client.get("/api/v1/remote-access/push/jobs", headers=_auth(admin_token)).json()["runner"]
    client.post("/api/v1/remote-access/runner/claim", json={"runner": "ADMIN-PC"}, headers=RUNNER)
    after = client.get("/api/v1/remote-access/push/jobs", headers=_auth(admin_token)).json()["runner"]

    assert before == {"name": None, "seconds_ago": None, "online": False}
    assert after["name"] == "ADMIN-PC" and after["online"] is True and after["seconds_ago"] < 30
