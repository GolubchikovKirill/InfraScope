from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlmodel import select

from app.domains.inventory.models import Computer, MediaPlayer
from app.domains.operations.models import CashRegister
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


def _dev(db_session, hostname: str) -> RemoteAccessDevice:
    return db_session.exec(
        select(RemoteAccessDevice).where(RemoteAccessDevice.hostname == hostname)
    ).first()


def test_seed_from_inventory_covers_registers_computers_and_nettops(db_session) -> None:
    db_session.add(Computer(hostname="VNA-MGR-101", location="A1"))
    db_session.add(Computer(hostname="VNA-MGR-102", location="A1"))
    db_session.add(
        CashRegister(kkm_number="K1", hostname="VNA-POS-01", store_number="099", kkm_type="retail")
    )
    db_session.add(
        MediaPlayer(
            device_type="nettop", name="TV-hall", model="nettop",
            ip_address="10.0.0.5", hostname="VNA-TV-01",
        )
    )
    db_session.add(
        MediaPlayer(
            device_type="iconbit", name="stick", model="iconbit",
            ip_address="10.0.0.6", hostname="VNA-STICK-01",
        )
    )
    db_session.commit()

    created = service.seed_from_inventory(db_session)
    assert created == 4  # 2 computers + 1 till + 1 nettop; the iconbit stick is skipped
    assert service.seed_from_inventory(db_session) == 0  # idempotent

    comp = _dev(db_session, "VNA-MGR-101")
    assert comp.rustdesk_id == "VNA_MGR_101" and comp.location == "A1"
    assert comp.source_kind == "computer" and comp.computer_id is not None

    till = _dev(db_session, "VNA-POS-01")
    assert till.source_kind == "cash_register" and till.cash_register_id is not None
    assert till.location == "099"

    tv = _dev(db_session, "VNA-TV-01")
    assert tv.source_kind == "media_player" and tv.media_player_id is not None

    assert _dev(db_session, "VNA-STICK-01") is None


def test_seed_marks_till_that_is_also_a_computer_as_cash_register(db_session) -> None:
    db_session.add(Computer(hostname="VNA-POS-09", location="Z1"))
    db_session.add(CashRegister(kkm_number="K9", hostname="VNA-POS-09", store_number="042"))
    db_session.commit()

    service.seed_from_inventory(db_session)
    dev = _dev(db_session, "VNA-POS-09")
    assert dev.source_kind == "cash_register"  # cash_register outranks computer
    assert dev.computer_id is not None and dev.cash_register_id is not None


def test_refresh_status_writes_host_online_not_rustdesk_online(db_session) -> None:
    polled = datetime.now(UTC) - timedelta(minutes=1)
    db_session.add(Computer(hostname="VNA-MGR-77", location="A1", is_online=True, last_polled_at=polled))
    db_session.commit()
    service.seed_from_inventory(db_session)

    touched = service.refresh_status_from_inventory(db_session)
    assert touched == 1
    dev = _dev(db_session, "VNA-MGR-77")
    # inventory reachability lands on host_online; the RustDesk-console field stays untouched
    assert dev.host_online is True and dev.host_last_seen_at is not None
    assert dev.online is None and dev.last_seen_at is None


def test_enqueue_first_deploy_mints_password_and_moves_to_queued(db_session) -> None:
    dev = RemoteAccessDevice(hostname="VNA-MGR-901")
    db_session.add(dev)
    db_session.commit()
    assert not dev.permanent_password

    jobs = service.enqueue(db_session, [dev], "deploy", created_by="tester@x")
    assert len(jobs) == 1
    db_session.refresh(dev)
    assert dev.permanent_password  # per-machine password minted
    assert dev.deploy_state == "queued"  # nothing installing until an agent claims it
    assert jobs[0].action == "deploy"
    assert jobs[0].status == "queued"


def test_claim_moves_device_from_queued_to_installing(db_session) -> None:
    dev = RemoteAccessDevice(hostname="VNA-MGR-902", permanent_password="x")
    db_session.add(dev)
    db_session.commit()
    service.enqueue(db_session, [dev], "deploy", created_by=None)
    db_session.refresh(dev)
    assert dev.deploy_state == "queued"

    service.claim_next_job(db_session, "agent-1")
    db_session.refresh(dev)
    assert dev.deploy_state == "installing"


def test_claim_prefers_deploy_over_rotate_for_the_same_device(db_session) -> None:
    dev = RemoteAccessDevice(hostname="VNA-MGR-903", permanent_password="x")
    db_session.add(dev)
    db_session.commit()
    # rotate queued first, deploy second - deploy must still go out first
    service.enqueue(db_session, [dev], "rotate_password", created_by=None)
    service.enqueue(db_session, [dev], "deploy", created_by=None)

    first = service.claim_next_job(db_session, "agent-1")
    assert first.action == "deploy"


def test_two_agents_never_claim_the_same_job(db_session) -> None:
    dev = RemoteAccessDevice(hostname="VNA-MGR-906", permanent_password="x")
    db_session.add(dev)
    db_session.commit()
    service.enqueue(db_session, [dev], "deploy", created_by=None)

    a = service.claim_next_job(db_session, "agent-a")
    b = service.claim_next_job(db_session, "agent-b")
    assert a is not None and b is None
    assert a.claimed_by == "agent-a" and a.attempts == 1


def test_reclaim_expires_jobs_no_agent_ever_claimed(db_session, monkeypatch) -> None:
    from app.core.config import settings as _s

    monkeypatch.setattr(_s, "RUSTDESK_JOB_QUEUED_TTL_HOURS", 24, raising=False)
    dev = RemoteAccessDevice(hostname="VNA-MGR-904", permanent_password="x")
    db_session.add(dev)
    db_session.commit()
    (job,) = service.enqueue(db_session, [dev], "deploy", created_by=None)
    job.created_at = datetime.now(UTC) - timedelta(hours=48)
    db_session.add(job)
    db_session.commit()

    assert service.reclaim_stale_jobs(db_session) == 1
    db_session.refresh(job)
    db_session.refresh(dev)
    assert job.status == "failed" and "expired" in (job.result_detail or "")
    assert dev.deploy_state == "failed"


def test_agent_health_flags_stall_when_queue_and_no_claims(db_session) -> None:
    dev = RemoteAccessDevice(hostname="VNA-MGR-905", permanent_password="x")
    db_session.add(dev)
    db_session.commit()
    service.enqueue(db_session, [dev], "deploy", created_by=None)

    h = service.agent_health(db_session)
    assert h["queued"] == 1 and h["last_claim_at"] is None and h["agent_stalled"] is True


def test_unmanaged_devices_are_skipped_by_enqueue(db_session) -> None:
    dev = RemoteAccessDevice(hostname="VNA-MGR-15", managed=False)
    db_session.add(dev)
    db_session.commit()
    assert service.enqueue(db_session, [dev], "reconfigure", created_by=None) == []


def test_prepare_device_creates_links_sets_id_and_queues_deploy(db_session) -> None:
    db_session.add(CashRegister(kkm_number="K7", hostname="VNA-POS-07", store_number="007"))
    db_session.commit()

    dev, job = service.prepare_device(
        db_session,
        hostname="VNA-POS-07",
        rustdesk_id="VNA_POS_07",
        permanent_password="kentdful",
        action="deploy",
        created_by="admin@x",
    )
    assert dev.source_kind == "cash_register" and dev.cash_register_id is not None
    assert dev.rustdesk_id == "VNA_POS_07" and dev.permanent_password == "kentdful"
    assert dev.deploy_state == "queued"
    assert job is not None and job.action == "deploy"

    # second call while the job is open returns that same job, mints nothing new
    dev2, job2 = service.prepare_device(
        db_session,
        hostname="VNA-POS-07",
        rustdesk_id=None,
        permanent_password=None,
        action="deploy",
        created_by="admin@x",
    )
    assert job2 is not None and job2.id == job.id
    assert dev2.permanent_password == "kentdful"


def test_prepare_device_mints_password_when_none_given(db_session) -> None:
    dev, job = service.prepare_device(
        db_session,
        hostname="VNA-MGR-500",
        rustdesk_id=None,
        permanent_password=None,
        action="deploy",
        created_by=None,
    )
    assert dev.rustdesk_id == "VNA_MGR_500"
    assert dev.permanent_password and dev.permanent_password.isalnum()
    assert job is not None


def test_enqueue_dedupes_while_a_job_is_still_open(db_session) -> None:
    dev = RemoteAccessDevice(hostname="VNA-MGR-16", permanent_password="x")
    db_session.add(dev)
    db_session.commit()

    first = service.enqueue(db_session, [dev], "reconfigure", created_by=None)
    assert len(first) == 1
    # same action again before the first finishes -> no new row
    assert service.enqueue(db_session, [dev], "reconfigure", created_by=None) == []
    open_jobs = db_session.exec(
        select(RemoteAccessDeployJob).where(RemoteAccessDeployJob.device_id == dev.id)
    ).all()
    assert len(open_jobs) == 1


def test_reclaim_stale_jobs_requeues_then_fails_after_retries(db_session) -> None:
    dev = RemoteAccessDevice(hostname="VNA-MGR-17", permanent_password="x")
    db_session.add(dev)
    db_session.commit()
    (job,) = service.enqueue(db_session, [dev], "deploy", created_by=None)
    claimed = service.claim_next_job(db_session, "agent-x")
    claimed.claimed_at = datetime.now(UTC) - timedelta(hours=2)
    db_session.add(claimed)
    db_session.commit()

    assert service.reclaim_stale_jobs(db_session) == 1
    db_session.refresh(job)
    assert job.status == "queued" and job.claimed_by is None

    # burn through attempts -> next reclaim fails it
    job.attempts = 3
    job.status = "claimed"
    job.claimed_at = datetime.now(UTC) - timedelta(hours=2)
    db_session.add(job)
    db_session.commit()
    assert service.reclaim_stale_jobs(db_session) == 1
    db_session.refresh(job)
    assert job.status == "failed"


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


def test_resolve_scope_by_ids_location_kind_and_all(db_session) -> None:
    a = RemoteAccessDevice(hostname="h-a", location="A1", source_kind="computer")
    b = RemoteAccessDevice(hostname="h-b", location="A2", source_kind="cash_register")
    c = RemoteAccessDevice(hostname="h-c", location="A1", managed=False)
    db_session.add_all([a, b, c])
    db_session.commit()

    assert {d.hostname for d in service.resolve_scope(db_session, device_ids=[a.id], location=None, all_managed=False)} == {
        "h-a"
    }
    # bulk scopes never touch unmanaged endpoints, so h-c is excluded
    assert {d.hostname for d in service.resolve_scope(db_session, device_ids=None, location="A1", all_managed=False)} == {
        "h-a",
    }
    assert {d.hostname for d in service.resolve_scope(db_session, device_ids=None, location=None, all_managed=True)} == {
        "h-a",
        "h-b",
    }
    assert {
        d.hostname
        for d in service.resolve_scope(
            db_session, device_ids=None, location=None, all_managed=True, source_kind="computer"
        )
    } == {"h-a"}
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
