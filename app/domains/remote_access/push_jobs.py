"""The queue behind "roll RustDesk out over the network" - and who runs it.

A push job is a request "install/configure RustDesk on this device now". Queueing
(`enqueue_push_jobs`) only ever writes rows; the actual push runs in a Celery task
(`execute_push_job`, dispatched right after queueing - see
`app.worker.tasks.remote_access_push_job_task`), over WinRM
(`app.domains.remote_access.winrm_exec`), not from an external runner process.

What a push does NOT do: write the device's `deploy_state` to "configured". That
state only ever changes through `service.apply_deploy_report`, called when the
device itself calls `/deploy/report` after installing - the same self-report the
pull/GPO rollout already relies on. A push job's own `state` only says whether the
*trigger* ran to completion (the WinRM command blocks until the whole install
finishes, so its exit code is meaningful - see `deploy_script.deploy_command`'s
`exit 1` in its failure branch) - never whether the device picked up the config.
Keeping that boundary means only the device's own authenticated call can ever
claim "I'm configured", regardless of what the backend's own WinRM call returned.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import overload

from sqlmodel import Session, col, select

from app.domains.remote_access import deploy_script, service, winrm_exec
from app.domains.remote_access.models import PUSH_JOB_ACTIVE, RemoteAccessDevice, RemoteAccessPushJob

logger = logging.getLogger(__name__)

# a job stuck "running" past this long means the worker process that owned it died
# mid-push (killed, OOM, deploy) - treated the same as a failed push, not retried
# automatically (see reap_stale_push_jobs).
RUNNING_JOB_TIMEOUT = timedelta(minutes=10)
MAX_JOBS_PER_REQUEST = 200


def _now() -> datetime:
    return datetime.now(UTC)


@overload
def _aware(value: datetime) -> datetime: ...
@overload
def _aware(value: None) -> None: ...
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
        for job in session.exec(select(RemoteAccessPushJob).where(col(RemoteAccessPushJob.state).in_(PUSH_JOB_ACTIVE))).all()
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
    """Only a job nobody has started on can be cancelled; a running push cannot be recalled."""
    if job.state != "queued":
        return False
    job.state = "cancelled"
    job.detail = "отменено оператором"
    job.finished_at = _now()
    session.add(job)
    session.commit()
    return True


def reap_stale_push_jobs(session: Session) -> int:
    """A job that stayed 'running' past the timeout was abandoned (its worker was
    killed or restarted mid-push).

    Fail it, and say so on the device: without this the machine would show
    "разворачивается" for ever.
    """
    limit = _now() - RUNNING_JOB_TIMEOUT
    reaped = 0
    for job in session.exec(select(RemoteAccessPushJob).where(RemoteAccessPushJob.state == "running")).all():
        started = _aware(job.started_at)
        if started is None or started > limit:
            continue
        job.state = "failed"
        job.detail = "воркер не отчитался за 10 минут (перезапущен или упал)"
        job.finished_at = _now()
        session.add(job)
        reaped += 1
    if reaped:
        session.commit()
    return reaped


def list_push_jobs(session: Session, limit: int = 100) -> list[RemoteAccessPushJob]:
    reap_stale_push_jobs(session)
    return list(
        session.exec(select(RemoteAccessPushJob).order_by(col(RemoteAccessPushJob.created_at).desc()).limit(limit)).all()
    )


# --------------------------------------------------------------------------- #
# running a job                                                               #
# --------------------------------------------------------------------------- #
def execute_push_job(session: Session, job: RemoteAccessPushJob) -> RemoteAccessPushJob:
    """Run one queued job over WinRM and close it. Called from the Celery task
    right after `enqueue_push_jobs` commits - see the module docstring for what
    this does and does not change on the device.
    """
    if job.state != "queued":
        return job  # raced with a cancel, or already picked up
    job.state = "running"
    job.started_at = _now()
    session.add(job)
    session.commit()
    session.refresh(job)

    dev = session.get(RemoteAccessDevice, job.device_id) if job.device_id else None
    if dev is None or not dev.managed:
        job.state = "skipped"
        job.detail = "машина больше не в управлении"
        job.finished_at = _now()
        session.add(job)
        session.commit()
        session.refresh(job)
        return job

    try:
        if job.dry_run:
            result = winrm_exec.probe(job.hostname)
        else:
            # The job's profile may differ from the device's own stored one (an
            # operator can push with an explicit profile) - apply it first so the
            # device's self-fetched config (GET /deploy/config) matches what was
            # asked for; apply_deploy_profile is the same function console-peer
            # adoption uses for the identical reason.
            service.apply_deploy_profile(session, dev, job.profile)
            service.mark_deploy_requested(session, dev)
            result = winrm_exec.run_powershell(job.hostname, deploy_script.deploy_command())
    except winrm_exec.WinRMNotConfiguredError as exc:
        job.state = "failed"
        job.detail = str(exc)
        job.finished_at = _now()
        session.add(job)
        session.commit()
        session.refresh(job)
        return job

    job.state = "succeeded" if result.ok else "failed"
    job.detail = result.detail[:1024] if result.detail else None
    job.finished_at = _now()
    session.add(job)
    session.commit()
    session.refresh(job)
    return job
