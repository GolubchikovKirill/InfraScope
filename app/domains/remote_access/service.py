"""Reconciliation between the RustDesk console, InfraScope inventory and deploy jobs."""

from __future__ import annotations

import logging
import secrets
import string
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, update
from sqlmodel import Session, select

from app.core.config import settings
from app.domains.inventory.models import Computer, MediaPlayer
from app.domains.operations.models import CashRegister
from app.domains.remote_access import rustdesk_client
from app.domains.remote_access.models import RemoteAccessDeployJob, RemoteAccessDevice

logger = logging.getLogger(__name__)

# only nettop media players are Windows boxes; iconbit/twix are Android sticks
_NETTOP = "nettop"
# a host can sit in two inventory tables (a till also tracked as a computer);
# the higher-ranked source owns its source_kind label
_SOURCE_RANK = {"cash_register": 3, "computer": 2, "media_player": 1}
# open jobs (not yet finished) - used for enqueue de-duplication
_OPEN_JOB_STATUSES = ("queued", "claimed", "running")

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


def _cr_location(cr: CashRegister) -> str | None:
    return cr.store_number or cr.store_code or None


def _link_inventory(session: Session, dev: RemoteAccessDevice) -> None:
    """(Re)bind a device row to every inventory row that shares its hostname."""
    host = dev.hostname
    if dev.computer_id is None:
        comp = session.exec(select(Computer).where(Computer.hostname == host)).first()
        if comp:
            dev.computer_id = comp.id
            dev.location = dev.location or comp.location
    if dev.cash_register_id is None:
        cr = session.exec(select(CashRegister).where(CashRegister.hostname == host)).first()
        if cr:
            dev.cash_register_id = cr.id
            dev.location = dev.location or _cr_location(cr)
    if dev.media_player_id is None:
        mp = session.exec(
            select(MediaPlayer).where(
                MediaPlayer.hostname == host, MediaPlayer.device_type == _NETTOP
            )
        ).first()
        if mp:
            dev.media_player_id = mp.id
    # label by the strongest source that actually linked (cash_register > computer > media_player)
    linked_kind = (
        "cash_register" if dev.cash_register_id
        else "computer" if dev.computer_id
        else "media_player" if dev.media_player_id
        else None
    )
    if linked_kind:
        dev.source_kind = linked_kind


def _inventory_rows(session: Session) -> list[tuple[str, str, str | None]]:
    """(hostname, source_kind, location) for every RustDesk-capable inventory endpoint.

    Cash registers and computers are Windows by definition; of the media players
    only nettops are (iconbit/twix run Android).
    """
    rows: list[tuple[str, str, str | None]] = []
    for cr in session.exec(select(CashRegister)).all():
        if cr.hostname and cr.hostname.strip():
            rows.append((cr.hostname.strip(), "cash_register", _cr_location(cr)))
    for host, loc in session.exec(select(Computer.hostname, Computer.location)).all():
        if host and host.strip():
            rows.append((host.strip(), "computer", loc))
    for host, name in session.exec(
        select(MediaPlayer.hostname, MediaPlayer.name).where(MediaPlayer.device_type == _NETTOP)
    ).all():
        if host and host.strip():
            rows.append((host.strip(), "media_player", None))
    return rows


def seed_from_inventory(session: Session) -> int:
    """Mirror the InfraScope endpoint inventory into RemoteAccessDevice rows.

    Sources: every CashRegister, every Computer, and MediaPlayers of type 'nettop'.
    Idempotent - an existing row only gets its inventory links, source_kind and
    (if still blank) location refreshed; its desired config and password are never
    touched here.
    """
    existing = {d.hostname: d for d in session.exec(select(RemoteAccessDevice)).all()}
    created = 0
    for hostname, kind, location in _inventory_rows(session):
        dev = existing.get(hostname)
        if dev is None:
            dev = RemoteAccessDevice(
                hostname=hostname,
                rustdesk_id=_hostname_to_rid(hostname),
                source_kind=kind,
                location=location,
            )
            existing[hostname] = dev
            session.add(dev)
            created += 1
        else:
            if _SOURCE_RANK.get(kind, 0) > _SOURCE_RANK.get(dev.source_kind, 0):
                dev.source_kind = kind
            if not dev.location and location:
                dev.location = location
        _link_inventory(session, dev)
    session.commit()
    return created


def refresh_status_from_inventory(session: Session) -> int:
    """Copy InfraScope's own reachability result onto the device as `host_online`.

    This is a *separate* signal from `online` (which is RustDesk-console truth):
    the host answering a ping tells you nothing about whether the RustDesk client
    is running or connected. The UI shows the two side by side.
    """
    updated = 0
    for dev in session.exec(select(RemoteAccessDevice)).all():
        inv_online, inv_polled = _inventory_status(session, dev)
        if inv_online is None:
            continue
        if dev.host_online != inv_online or dev.host_last_seen_at != inv_polled:
            dev.host_online = inv_online
            dev.host_last_seen_at = inv_polled
            dev.updated_at = _now()
            updated += 1
    if updated:
        session.commit()
    return updated


def _inventory_status(session: Session, dev: RemoteAccessDevice) -> tuple[bool | None, datetime | None]:
    for model, fk in (
        (Computer, dev.computer_id),
        (CashRegister, dev.cash_register_id),
        (MediaPlayer, dev.media_player_id),
    ):
        if fk is None:
            continue
        row = session.get(model, fk)
        if row is not None:
            return row.is_online, row.last_polled_at
    return None, None


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
def prepare_device(
    session: Session,
    *,
    hostname: str,
    rustdesk_id: str | None,
    permanent_password: str | None,
    action: str,
    created_by: str | None,
) -> tuple[RemoteAccessDevice, RemoteAccessDeployJob | None]:
    """One call behind the RustDesk buttons on the device cards: create/link the
    endpoint, stamp its id + password, and queue a deploy that installs the
    client, points it at our server and applies the lockdown.
    """
    dev = _get_or_create_device(session, hostname)
    _link_inventory(session, dev)
    if rustdesk_id:
        dev.rustdesk_id = rustdesk_id
    elif not dev.rustdesk_id:
        dev.rustdesk_id = _hostname_to_rid(hostname)
    if permanent_password:
        dev.permanent_password = permanent_password
        dev.password_rotated_at = _now()
    elif not dev.permanent_password:
        dev.permanent_password = generate_password()
        dev.password_rotated_at = _now()
    dev.managed = True
    dev.updated_at = _now()
    session.add(dev)
    session.flush()

    existing = _open_job(session, dev.id, action)
    job = existing or _enqueue_one(session, dev, action, created_by=created_by)
    session.commit()
    session.refresh(dev)
    if job:
        session.refresh(job)
    return dev, job


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


def _open_job(session: Session, device_id: uuid.UUID, action: str) -> RemoteAccessDeployJob | None:
    return session.exec(
        select(RemoteAccessDeployJob).where(
            RemoteAccessDeployJob.device_id == device_id,
            RemoteAccessDeployJob.action == action,
            RemoteAccessDeployJob.status.in_(_OPEN_JOB_STATUSES),  # type: ignore[attr-defined]
        )
    ).first()


def _enqueue_one(
    session: Session, dev: RemoteAccessDevice, action: str, *, created_by: str | None
) -> RemoteAccessDeployJob:
    # de-dupe: a second identical click while the first job is still open is a no-op
    existing = _open_job(session, dev.id, action)
    if existing is not None:
        return existing
    job = RemoteAccessDeployJob(
        device_id=dev.id,
        hostname=dev.hostname,
        action=action,
        params=_job_params(dev),
        created_by=created_by,
    )
    session.add(job)
    if action in ("deploy", "reconfigure", "rotate_password", "set_lockdown"):
        # only "queued" here - nothing is being installed until an agent claims it
        dev.deploy_state = "queued"
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
        if _open_job(session, dev.id, action) is not None:
            continue  # identical job already in flight
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
# what an agent should pick up first: install the client before fiddling with it
_ACTION_PRIORITY = {"deploy": 0, "reconfigure": 1, "set_lockdown": 2, "rotate_password": 3, "uninstall": 4}


def claim_next_job(session: Session, agent_id: str) -> RemoteAccessDeployJob | None:
    # candidates ordered by (action priority, age); claim the first one that a
    # concurrent agent hasn't grabbed. The conditional UPDATE is the guard - it
    # only flips a row that is still 'queued', so two agents never take the same
    # job (works on SQLite and Postgres alike; no SELECT ... FOR UPDATE needed).
    candidates = session.exec(
        select(RemoteAccessDeployJob)
        .where(RemoteAccessDeployJob.status == "queued")
        .order_by(RemoteAccessDeployJob.created_at)
    ).all()
    candidates.sort(key=lambda j: _ACTION_PRIORITY.get(j.action, 9))

    now = _now()
    for job in candidates:
        won = session.exec(
            update(RemoteAccessDeployJob)
            .where(RemoteAccessDeployJob.id == job.id, RemoteAccessDeployJob.status == "queued")
            .values(status="claimed", claimed_by=agent_id, claimed_at=now, attempts=job.attempts + 1, updated_at=now)
        ).rowcount
        if not won:
            continue  # another agent claimed it between the select and now
        session.commit()
        session.expire(job)
        dev = session.get(RemoteAccessDevice, job.device_id)
        if dev and dev.deploy_state == "queued":
            dev.deploy_state = "installing"  # now something is actually happening
            dev.updated_at = now
            session.add(dev)
            session.commit()
        session.refresh(job)
        return job
    return None


def agent_last_claim_at(session: Session) -> datetime | None:
    row = session.exec(
        select(RemoteAccessDeployJob.claimed_at)
        .where(RemoteAccessDeployJob.claimed_at.is_not(None))  # type: ignore[attr-defined]
        .order_by(RemoteAccessDeployJob.claimed_at.desc())  # type: ignore[attr-defined]
    ).first()
    return row


def agent_health(session: Session) -> dict:
    """Small status summary for the page header: is anything draining the queue."""
    queued = session.exec(
        select(func.count()).select_from(RemoteAccessDeployJob).where(RemoteAccessDeployJob.status == "queued")
    ).one()
    running = session.exec(
        select(func.count())
        .select_from(RemoteAccessDeployJob)
        .where(RemoteAccessDeployJob.status.in_(("claimed", "running")))  # type: ignore[attr-defined]
    ).one()
    last_claim = agent_last_claim_at(session)
    silent_for = (_now() - last_claim).total_seconds() / 60 if last_claim else None
    stalled = bool(
        queued
        and (last_claim is None or silent_for > settings.RUSTDESK_AGENT_SILENT_MINUTES)
    )
    return {
        "queued": int(queued),
        "running": int(running),
        "last_claim_at": last_claim.isoformat() if last_claim else None,
        "agent_stalled": stalled,
    }


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
        if status == "running" and dev.deploy_state in ("queued", "unknown"):
            dev.deploy_state = "installing"
        if status == "done":
            dev.deploy_state = facts.get("deploy_state") or (
                "not_installed" if job.action == "uninstall" else "configured"
            )
            dev.last_deployed_at = now
            dev.last_error = None
            # the agent only reports a password action "done" after verifying the
            # hash actually persisted on the box (Rotate-Password / Deploy-Client)
            if job.action in ("deploy", "reconfigure", "rotate_password"):
                dev.password_confirmed_at = now
        elif status == "failed":
            dev.deploy_state = "failed"
            dev.last_error = (detail or "")[:1024]
        dev.updated_at = now
        session.add(dev)
    session.add(job)
    session.commit()


def reclaim_stale_jobs(session: Session) -> int:
    """Housekeeping for jobs that will never finish on their own.

    * claimed/running with no report for RUSTDESK_JOB_STALE_MINUTES -> back to
      queued (agent crashed / lost network); failed after 3 attempts.
    * queued for longer than RUSTDESK_JOB_QUEUED_TTL_HOURS -> failed (no agent
      ever picked it up) so the grid stops showing phantom pending work.
    """
    now = _now()
    n = 0

    stale_cutoff = now - timedelta(minutes=settings.RUSTDESK_JOB_STALE_MINUTES)
    stuck = session.exec(
        select(RemoteAccessDeployJob).where(
            RemoteAccessDeployJob.status.in_(("claimed", "running")),  # type: ignore[attr-defined]
            RemoteAccessDeployJob.claimed_at < stale_cutoff,
        )
    ).all()
    for job in stuck:
        if job.attempts >= 3:
            job.status = "failed"
            job.finished_at = now
            job.result_detail = (job.result_detail or "") + " [reclaimed: agent never reported]"
            dev = session.get(RemoteAccessDevice, job.device_id)
            if dev and dev.deploy_state in ("queued", "installing"):
                dev.deploy_state = "failed"
                dev.last_error = "deploy agent stopped responding mid-job"
                session.add(dev)
        else:
            job.status = "queued"
            job.claimed_by = None
            job.claimed_at = None
            job.started_at = None
        job.updated_at = now
        session.add(job)
        n += 1

    ttl_cutoff = now - timedelta(hours=settings.RUSTDESK_JOB_QUEUED_TTL_HOURS)
    abandoned = session.exec(
        select(RemoteAccessDeployJob).where(
            RemoteAccessDeployJob.status == "queued",
            RemoteAccessDeployJob.created_at < ttl_cutoff,
        )
    ).all()
    for job in abandoned:
        job.status = "failed"
        job.finished_at = now
        job.result_detail = (
            (job.result_detail or "") + f" [expired: no agent claimed it within "
            f"{settings.RUSTDESK_JOB_QUEUED_TTL_HOURS}h]"
        )
        job.updated_at = now
        session.add(job)
        dev = session.get(RemoteAccessDevice, job.device_id)
        if dev and dev.deploy_state == "queued" and _open_job(session, dev.id, job.action) is None:
            dev.deploy_state = "failed"
            dev.last_error = "deploy job expired: no agent is running"
            dev.updated_at = now
            session.add(dev)
        n += 1

    if n:
        session.commit()
    return n


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
    session: Session,
    *,
    device_ids: list[uuid.UUID] | None,
    location: str | None,
    all_managed: bool,
    source_kind: str | None = None,
) -> list[RemoteAccessDevice]:
    stmt = select(RemoteAccessDevice)
    if device_ids:
        stmt = stmt.where(RemoteAccessDevice.id.in_(device_ids))  # type: ignore[attr-defined]
    elif location or source_kind or all_managed:
        # any of these bulk scopes only ever touches managed endpoints
        stmt = stmt.where(RemoteAccessDevice.managed == True)  # noqa: E712
        if location:
            stmt = stmt.where(RemoteAccessDevice.location == location)
        if source_kind:
            stmt = stmt.where(RemoteAccessDevice.source_kind == source_kind)
    else:
        return []
    return list(session.exec(stmt).all())
