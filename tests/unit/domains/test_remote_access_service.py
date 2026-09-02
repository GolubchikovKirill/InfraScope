from __future__ import annotations

import uuid

from app.domains.inventory.models import Computer
from app.domains.remote_access import service
from app.domains.remote_access.models import RemoteAccessDeployJob, RemoteAccessDevice


def test_generate_password_is_long_and_alnum() -> None:
    pw = service.generate_password()
    assert len(pw) == 20
    assert pw.isalnum()
    assert service.generate_password() != service.generate_password()


def test_hostname_to_rid_replaces_disallowed_chars() -> None:
    assert service._hostname_to_rid("VNK-MGR-D1") == "VNK_MGR_D1"
    assert service._hostname_to_rid("a" * 40) == "a" * 32


def test_seed_from_inventory_creates_one_device_per_computer(db_session) -> None:
    db_session.add(Computer(hostname="VNA-MGR-101", location="A1"))
    db_session.add(Computer(hostname="VNA-MGR-102", location="A1"))
    db_session.commit()

    created = service.seed_from_inventory(db_session)
    assert created == 2
    # idempotent
    assert service.seed_from_inventory(db_session) == 0

    dev = db_session.exec(
        __import__("sqlmodel").select(RemoteAccessDevice).where(RemoteAccessDevice.hostname == "VNA-MGR-101")
    ).first()
    assert dev is not None
    assert dev.rustdesk_id == "VNA_MGR_101"
    assert dev.location == "A1"


def test_enqueue_first_deploy_mints_a_password_and_moves_to_installing(db_session) -> None:
    dev = RemoteAccessDevice(hostname="VNA-MGR-901")
    db_session.add(dev)
    db_session.commit()
    assert not dev.permanent_password

    jobs = service.enqueue(db_session, [dev], "deploy", created_by="tester@x")
    assert len(jobs) == 1
    db_session.refresh(dev)
    assert dev.permanent_password  # per-machine password minted
    assert dev.deploy_state == "installing"
    assert jobs[0].action == "deploy"
    assert jobs[0].status == "queued"


def test_unmanaged_devices_are_skipped_by_enqueue(db_session) -> None:
    dev = RemoteAccessDevice(hostname="VNA-MGR-15", managed=False)
    db_session.add(dev)
    db_session.commit()
    assert service.enqueue(db_session, [dev], "reconfigure", created_by=None) == []


def test_rotate_password_changes_secret_and_queues_job(db_session) -> None:
    dev = RemoteAccessDevice(hostname="VNK-MGR-D1", permanent_password="old")
    db_session.add(dev)
    db_session.commit()

    job = service.rotate_password(db_session, dev, created_by="tester@x")
    db_session.commit()
    db_session.refresh(dev)
    assert dev.permanent_password not in ("", "old")
    assert dev.password_rotated_at is not None
    assert job.action == "rotate_password"


def test_claim_and_report_job_state_machine(db_session) -> None:
    dev = RemoteAccessDevice(hostname="VNA-MGR-204", permanent_password="secret123")
    db_session.add(dev)
    db_session.commit()
    (job,) = service.enqueue(db_session, [dev], "deploy", created_by=None)

    claimed = service.claim_next_job(db_session, "agent-1")
    assert claimed is not None and claimed.id == job.id
    assert claimed.status == "claimed" and claimed.claimed_by == "agent-1" and claimed.attempts == 1
    # nothing left to claim
    assert service.claim_next_job(db_session, "agent-1") is None

    assert service.job_secret(db_session, claimed) == "secret123"

    service.report_job(
        db_session,
        claimed,
        status="done",
        detail="applied deploy",
        facts={"installed_version": "1.4.9", "rustdesk_id": "VNA_MGR_204", "deploy_state": None},
    )
    db_session.refresh(job)
    db_session.refresh(dev)
    assert job.status == "done" and job.finished_at is not None
    assert dev.deploy_state == "configured"
    assert dev.installed_version == "1.4.9"
    assert dev.last_error is None


def test_report_failed_job_records_error(db_session) -> None:
    dev = RemoteAccessDevice(hostname="VNA-MGR-205", permanent_password="x")
    db_session.add(dev)
    db_session.commit()
    (job,) = service.enqueue(db_session, [dev], "reconfigure", created_by=None)
    claimed = service.claim_next_job(db_session, "agent-2")

    service.report_job(db_session, claimed, status="failed", detail="target unreachable on 445", facts={})
    db_session.refresh(dev)
    assert dev.deploy_state == "failed"
    assert "unreachable" in (dev.last_error or "")


def test_resolve_scope_by_ids_location_and_all(db_session) -> None:
    a = RemoteAccessDevice(hostname="h-a", location="A1")
    b = RemoteAccessDevice(hostname="h-b", location="A2")
    c = RemoteAccessDevice(hostname="h-c", location="A1", managed=False)
    db_session.add_all([a, b, c])
    db_session.commit()

    assert {d.hostname for d in service.resolve_scope(db_session, device_ids=[a.id], location=None, all_managed=False)} == {
        "h-a"
    }
    assert {d.hostname for d in service.resolve_scope(db_session, device_ids=None, location="A1", all_managed=False)} == {
        "h-a",
        "h-c",
    }
    assert {d.hostname for d in service.resolve_scope(db_session, device_ids=None, location=None, all_managed=True)} == {
        "h-a",
        "h-b",
    }
    assert service.resolve_scope(db_session, device_ids=None, location=None, all_managed=False) == []


def test_deploy_job_row_shape(db_session) -> None:
    dev = RemoteAccessDevice(hostname="h-x", permanent_password="x")
    db_session.add(dev)
    db_session.commit()
    (job,) = service.enqueue(db_session, [dev], "deploy", created_by="me")
    assert isinstance(job, RemoteAccessDeployJob)
    assert job.hostname == "h-x"
    assert job.params["id_server"]  # non-secret config snapshot
    assert "password" not in job.params
    assert isinstance(job.device_id, uuid.UUID)
