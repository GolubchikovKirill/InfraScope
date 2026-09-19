"""The queue behind "roll RustDesk out over the network" - and nothing that executes.

The server never runs anything on the fleet (from a Linux box that is lateral movement
and gets blocked). It keeps a queue of jobs; a runner on a Windows admin host (see
`deploy-runner/Run-PushRunner.ps1`) claims them, runs the push kit
(`rustdesk-ksc/Push-RustDesk.ps1`: C$ + WMI/DCOM, Windows 7 and 10, no reboot) and
reports the outcome. That report is what moves a device's rollout state, exactly like
the report of the pull script does.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from app.core.config import settings
from app.core.redis import REDIS_ERRORS, get_redis
from app.domains.remote_access import service
from app.domains.remote_access.models import PUSH_JOB_ACTIVE, RemoteAccessDevice, RemoteAccessPushJob

logger = logging.getLogger(__name__)

# a claimed job that has not been reported after this long means the runner died mid-push
RUNNING_JOB_TIMEOUT = timedelta(minutes=30)
# how long a runner counts as "connected" after its last claim
RUNNER_ONLINE_WITHIN = timedelta(seconds=90)
MAX_JOBS_PER_REQUEST = 200
_RUNNER_KEY = "remote-access:push-runner"

# what the runner may report for a job
RUNNER_RESULTS = ("ok", "warn", "failed", "skipped", "dry_run")


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


# --------------------------------------------------------------------------- #
# queueing                                                                    #
# --------------------------------------------------------------------------- #
def enqueue_push_jobs(
    session: Session,
    devices: list[RemoteAccessDevice],
    *,
    profile: str | None,
    dry_run: bool,
    requested_by: str | None,
) -> tuple[list[RemoteAccessPushJob], list[dict[str, str]]]:
    """Queue one job per device. Returns (queued, skipped-with-reason).

    Skipped: not managed (nobody asked for this machine to be run by us), Windows XP
    (RustDesk does not run there), or already has a job waiting or running.
    """
    if profile is not None and profile not in service.DEPLOY_PROFILES:
        raise ValueError(f"unknown deploy profile {profile!r}")
    busy = {
        job.device_id
        for job in session.exec(select(RemoteAccessPushJob).where(RemoteAccessPushJob.state.in_(PUSH_JOB_ACTIVE))).all()
        if job.device_id
    }
    queued: list[RemoteAccessPushJob] = []
    skipped: list[dict[str, str]] = []
    for dev in devices:
        if not dev.managed:
            skipped.append({"hostname": dev.hostname, "reason": "не в управлении"})
        elif "xp" in (dev.os_caption or "").lower().split():
            skipped.append({"hostname": dev.hostname, "reason": "Windows XP: RustDesk там не работает"})
        elif dev.id in busy:
            skipped.append({"hostname": dev.hostname, "reason": "уже в очереди или выполняется"})
        else:
            job = RemoteAccessPushJob(
                device_id=dev.id,
                hostname=dev.hostname,
                profile=profile or dev.deploy_profile,
                dry_run=dry_run,
                requested_by=requested_by,
            )
            session.add(job)
            queued.append(job)
    session.commit()
    for job in queued:
        session.refresh(job)
    return queued, skipped


def cancel_push_job(session: Session, job: RemoteAccessPushJob) -> bool:
    """Only a job nobody has claimed can be cancelled; a running push cannot be recalled."""
    if job.state != "queued":
        return False
    job.state = "cancelled"
    job.detail = "отменено оператором"
    job.finished_at = _now()
    session.add(job)
    session.commit()
    return True


def reap_stale_push_jobs(session: Session) -> int:
    """A job that stayed 'running' past the timeout was abandoned (runner closed or crashed).

    Fail it, and say so on the device: without this the machine would show "разворачивается"
    for ever.
    """
    limit = _now() - RUNNING_JOB_TIMEOUT
    reaped = 0
    for job in session.exec(select(RemoteAccessPushJob).where(RemoteAccessPushJob.state == "running")).all():
        started = _aware(job.started_at)
        if started is None or started > limit:
            continue
        detail = "раннер не отчитался за 30 минут (закрыт или упал)"
        job.state = "failed"
        job.detail = detail
        job.finished_at = _now()
        session.add(job)
        if not job.dry_run:
            service.apply_deploy_report(session, hostname=job.hostname, state="failed", detail=detail)
        reaped += 1
    if reaped:
        session.commit()
    return reaped


def list_push_jobs(session: Session, limit: int = 100) -> list[RemoteAccessPushJob]:
    reap_stale_push_jobs(session)
    return list(session.exec(select(RemoteAccessPushJob).order_by(RemoteAccessPushJob.created_at.desc()).limit(limit)).all())


# --------------------------------------------------------------------------- #
# what the runner does                                                        #
# --------------------------------------------------------------------------- #
def _job_config(job: RemoteAccessPushJob, dev: RemoteAccessDevice) -> dict:
    """The per-machine config the push kit is run with - the same values the address book
    holds for this machine, so the password on the machine matches the one the console
    hands an engineer."""
    config = service.package_config(dev)
    if settings.RUSTDESK_INSTALLER_FILENAME:
        config["installer_msi"] = settings.RUSTDESK_INSTALLER_FILENAME
    return config


def claim_push_jobs(session: Session, *, runner: str, limit: int) -> list[tuple[RemoteAccessPushJob, dict]]:
    """Hand the oldest queued jobs to a runner, marking them running.

    A job whose device is gone or no longer managed is closed as skipped instead of handed
    out: a machine taken out of management must not get RustDesk pushed at it.
    """
    reap_stale_push_jobs(session)
    statement = (
        select(RemoteAccessPushJob)
        .where(RemoteAccessPushJob.state == "queued")
        .order_by(RemoteAccessPushJob.created_at)
        .limit(max(1, limit))
        .with_for_update(skip_locked=True)
    )
    claimed: list[tuple[RemoteAccessPushJob, dict]] = []
    for job in session.exec(statement).all():
        dev = session.get(RemoteAccessDevice, job.device_id) if job.device_id else None
        if dev is None or not dev.managed:
            job.state = "skipped"
            job.detail = "машина больше не в управлении"
            job.finished_at = _now()
            session.add(job)
            continue
        job.state = "running"
        job.runner = runner[:64]
        job.started_at = _now()
        session.add(job)
        if not job.dry_run:
            service.mark_deploy_requested(session, dev)
        claimed.append((job, _job_config(job, dev)))
    session.commit()
    for job, _ in claimed:
        session.refresh(job)
    return claimed


def report_push_job(
    session: Session,
    job: RemoteAccessPushJob,
    *,
    result: str,
    detail: str | None,
    os_caption: str | None = None,
) -> RemoteAccessPushJob:
    """Apply the runner's verdict: close the job and, for a real push, move the device state.

    ok / warn  -> the client is installed and configured (warn keeps its warning in detail)
    failed     -> the device shows the failure
    skipped    -> the kit refused the machine (Windows XP); the device is left alone
    dry_run    -> a probe only; nothing changed on the machine, nothing changes here
    """
    if result not in RUNNER_RESULTS:
        raise ValueError(f"unknown result {result!r}")
    if job.state not in PUSH_JOB_ACTIVE:
        return job  # a late or repeated report for a job already closed
    text = (detail or "").strip()[:1024] or None
    job.state = {"ok": "succeeded", "warn": "succeeded", "dry_run": "succeeded", "failed": "failed", "skipped": "skipped"}[result]
    job.detail = ("предупреждение: " + text) if result == "warn" and text else text
    job.finished_at = _now()
    session.add(job)

    if not job.dry_run and result in ("ok", "warn", "failed"):
        service.apply_deploy_report(
            session,
            hostname=job.hostname,
            state="configured" if result in ("ok", "warn") else "failed",
            detail=text,
            os_caption=os_caption,
        )
    session.commit()
    session.refresh(job)
    return job


# --------------------------------------------------------------------------- #
# is a runner there?                                                          #
# --------------------------------------------------------------------------- #
async def note_runner_seen(name: str) -> None:
    """Remember the last runner that claimed. Best-effort: Redis being down must not stop a push."""
    try:
        redis = await get_redis()
        await redis.hset(_RUNNER_KEY, mapping={"name": name[:64], "at": _now().isoformat()})
        await redis.expire(_RUNNER_KEY, 86400)
    except REDIS_ERRORS as exc:
        logger.warning("Could not record the push runner heartbeat: %s", exc)


async def runner_status() -> dict:
    """{'name', 'seconds_ago', 'online'} of the last runner, or all-None when none has ever claimed."""
    empty = {"name": None, "seconds_ago": None, "online": False}
    try:
        redis = await get_redis()
        raw = await redis.hgetall(_RUNNER_KEY)
    except REDIS_ERRORS as exc:
        logger.warning("Could not read the push runner heartbeat: %s", exc)
        return empty
    if not raw:
        return empty
    data = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in raw.items()}
    try:
        seen = datetime.fromisoformat(data["at"])
    except (KeyError, ValueError):
        return empty
    ago = (_now() - _aware(seen)).total_seconds()
    return {"name": data.get("name"), "seconds_ago": int(ago), "online": ago <= RUNNER_ONLINE_WITHIN.total_seconds()}
