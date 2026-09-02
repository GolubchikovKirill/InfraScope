"""Reconciliation between the RustDesk console, InfraScope inventory and deploy jobs."""

from __future__ import annotations

import logging
import secrets
import string
import uuid
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from app.core.config import settings
from app.domains.inventory.models import Computer, MediaPlayer
from app.domains.remote_access import rustdesk_client
from app.domains.remote_access.models import RemoteAccessDeployJob, RemoteAccessDevice

logger = logging.getLogger(__name__)

_PW_ALPHABET = string.ascii_letters + string.digits  # no symbols: avoids shell/TOML quoting traps


def generate_password(length: int = 20) -> str:
    return "".join(secrets.choice(_PW_ALPHABET) for _ in range(length))


def _now() -> datetime:
    return datetime.now(UTC)


def _hostname_to_rid(hostname: str) -> str:
    # RustDesk custom IDs allow only [A-Za-z0-9_]; keep it <=16 where possible
    rid = "".join(c if c.isalnum() else "_" for c in hostname)
    return rid[:32]


# --------------------------------------------------------------------------- #
# device inventory sync                                                       #
# --------------------------------------------------------------------------- #
def _get_or_create_device(session: Session, hostname: str) -> RemoteAccessDevice:
    host = hostname.strip()
    dev = session.exec(select(RemoteAccessDevice).where(RemoteAccessDevice.hostname == host)).first()
    if dev:
        return dev
    dev = RemoteAccessDevice(hostname=host, rustdesk_id=_hostname_to_rid(host))
    session.add(dev)
    session.flush()
    return dev


def _link_inventory(session: Session, dev: RemoteAccessDevice) -> None:
    if dev.computer_id is None:
        comp = session.exec(select(Computer).where(Computer.hostname == dev.hostname)).first()
        if comp:
            dev.computer_id = comp.id
            dev.location = dev.location or comp.location
    if dev.media_player_id is None:
        mp = session.exec(
            select(MediaPlayer).where(MediaPlayer.hostname == dev.hostname)  # type: ignore[attr-defined]
        ).first() if hasattr(MediaPlayer, "hostname") else None
        if mp:
            dev.media_player_id = mp.id


def seed_from_inventory(session: Session) -> int:
    """Create RemoteAccessDevice rows for every Computer so untouched machines still show up."""
    created = 0
    existing = set(session.exec(select(RemoteAccessDevice.hostname)).all())
    for hostname in session.exec(select(Computer.hostname)).all():
        if hostname and hostname not in existing:
            dev = RemoteAccessDevice(hostname=hostname, rustdesk_id=_hostname_to_rid(hostname))
            _link_inventory(session, dev)
            session.add(dev)
            created += 1
    if created:
        session.commit()
    return created


async def sync_from_console(session: Session) -> dict[str, int]:
    """Pull the console peer list and fold live status into RemoteAccessDevice rows."""
    peers = await rustdesk_client.list_peers()
    stale_after = timedelta(seconds=settings.RUSTDESK_DEVICE_STALE_SECONDS)
    seen = 0
    for p in peers:
        hostname = (p.get("hostname") or p.get("host") or "").strip()
        if not hostname:
            continue
        seen += 1
        dev = _get_or_create_device(session, hostname)
        _link_inventory(session, dev)
        rid = str(p.get("id") or "").strip() or None
        if rid:
            dev.rustdesk_id = rid
        ver = str(p.get("version") or "").strip() or None
        if ver:
            dev.installed_version = ver
            if dev.deploy_state in ("unknown", "not_installed"):
                dev.deploy_state = "installed"
        dev.logged_in_user = (p.get("username") or p.get("user") or None) or dev.logged_in_user
        dev.last_ip = (p.get("last_online_ip") or p.get("ip") or None) or dev.last_ip
        ts = p.get("last_online_time") or p.get("last_online")
        if isinstance(ts, (int, float)) and ts > 0:
            dev.last_seen_at = datetime.fromtimestamp(ts, tz=UTC)
        elif isinstance(ts, str) and ts:
            try:
                dev.last_seen_at = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                pass
        dev.online = bool(dev.last_seen_at and (_now() - dev.last_seen_at) < stale_after)
        dev.updated_at = _now()
    session.commit()
    return {"peers_seen": seen}


# --------------------------------------------------------------------------- #
# desired-state actions                                                       #
# --------------------------------------------------------------------------- #
def rotate_password(session: Session, dev: RemoteAccessDevice, *, created_by: str | None) -> RemoteAccessDeployJob:
    dev.permanent_password = generate_password()
    dev.password_rotated_at = _now()
    dev.updated_at = _now()
    session.add(dev)
    return _enqueue_one(session, dev, "rotate_password", created_by=created_by)


def _job_params(dev: RemoteAccessDevice) -> dict:
    return {
        "installer_version": settings.RUSTDESK_INSTALLER_VERSION,
        "id_server": settings.RUSTDESK_ID_SERVER,
        "relay_server": settings.RUSTDESK_RELAY_SERVER,
        "hidden": dev.desired_hidden,
        "block_outgoing": dev.desired_block_outgoing,
        "unattended": dev.desired_unattended,
    }


def _enqueue_one(
    session: Session, dev: RemoteAccessDevice, action: str, *, created_by: str | None
) -> RemoteAccessDeployJob:
    job = RemoteAccessDeployJob(
        device_id=dev.id,
        hostname=dev.hostname,
        action=action,
        params=_job_params(dev),
        created_by=created_by,
    )
    session.add(job)
    if action in ("deploy", "reconfigure", "rotate_password", "set_lockdown"):
        dev.deploy_state = "installing"
        dev.updated_at = _now()
        session.add(dev)
    return job


def enqueue(
    session: Session,
    devices: list[RemoteAccessDevice],
    action: str,
    *,
    created_by: str | None,
) -> list[RemoteAccessDeployJob]:
    jobs: list[RemoteAccessDeployJob] = []
    for dev in devices:
        if not dev.managed:
            continue
        if action in ("deploy", "reconfigure") and not dev.permanent_password:
            # first deploy always ships a fresh per-machine password
            dev.permanent_password = generate_password()
            dev.password_rotated_at = _now()
            session.add(dev)
        jobs.append(_enqueue_one(session, dev, action, created_by=created_by))
    session.commit()
    return jobs


# --------------------------------------------------------------------------- #
# agent protocol                                                             #
# --------------------------------------------------------------------------- #
def claim_next_job(session: Session, agent_id: str) -> RemoteAccessDeployJob | None:
    job = session.exec(
        select(RemoteAccessDeployJob)
        .where(RemoteAccessDeployJob.status == "queued")
        .order_by(RemoteAccessDeployJob.created_at)
    ).first()
    if not job:
        return None
    job.status = "claimed"
    job.claimed_by = agent_id
    job.claimed_at = _now()
    job.attempts += 1
    job.updated_at = _now()
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def job_secret(session: Session, job: RemoteAccessDeployJob) -> str:
    dev = session.get(RemoteAccessDevice, job.device_id)
    return dev.permanent_password if dev else ""


def report_job(session: Session, job: RemoteAccessDeployJob, *, status: str, detail: str | None, facts: dict) -> None:
    now = _now()
    if status == "running" and job.started_at is None:
        job.started_at = now
    job.result_detail = (detail or "")[:2048] or job.result_detail
    job.updated_at = now
    if status in ("done", "failed"):
        job.status = status
        job.finished_at = now

    dev = session.get(RemoteAccessDevice, job.device_id)
    if dev:
        if facts.get("installed_version"):
            dev.installed_version = facts["installed_version"]
        if facts.get("rustdesk_id"):
            dev.rustdesk_id = facts["rustdesk_id"]
        if status == "done":
            dev.deploy_state = facts.get("deploy_state") or (
                "not_installed" if job.action == "uninstall" else "configured"
            )
            dev.last_deployed_at = now
            dev.last_error = None
        elif status == "failed":
            dev.deploy_state = "failed"
            dev.last_error = (detail or "")[:1024]
        dev.updated_at = now
        session.add(dev)
    session.add(job)
    session.commit()


def prune_finished_jobs(session: Session, older_than_days: int = 14) -> int:
    cutoff = _now() - timedelta(days=older_than_days)
    rows = session.exec(
        select(RemoteAccessDeployJob).where(
            RemoteAccessDeployJob.status.in_(("done", "failed", "cancelled")),  # type: ignore[attr-defined]
            RemoteAccessDeployJob.finished_at < cutoff,
        )
    ).all()
    for r in rows:
        session.delete(r)
    if rows:
        session.commit()
    return len(rows)


def resolve_scope(
    session: Session, *, device_ids: list[uuid.UUID] | None, location: str | None, all_managed: bool
) -> list[RemoteAccessDevice]:
    stmt = select(RemoteAccessDevice)
    if device_ids:
        stmt = stmt.where(RemoteAccessDevice.id.in_(device_ids))  # type: ignore[attr-defined]
    elif location:
        stmt = stmt.where(RemoteAccessDevice.location == location)
    elif all_managed:
        stmt = stmt.where(RemoteAccessDevice.managed == True)  # noqa: E712
    else:
        return []
    return list(session.exec(stmt).all())
