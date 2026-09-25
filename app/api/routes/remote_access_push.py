"""Network rollout of RustDesk, run by a Windows runner.

Two audiences:

* operators (a superuser session) queue pushes, look at the queue and cancel a waiting job;
* the runner (a script on a Windows admin host, no session) claims jobs and reports the
  outcome, authenticated by a shared token like the endpoint script is.

This server never executes anything on the fleet - see `push_jobs`.
"""

from __future__ import annotations

import hmac
import logging
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.api.routes._service_errors import not_found
from app.api.routes.remote_access import _client_ip, _rate_limit_key
from app.core.config import settings
from app.core.limiter import limiter
from app.domains.remote_access import push_jobs
from app.domains.remote_access.models import RemoteAccessDevice, RemoteAccessPushJob
from app.domains.remote_access.schemas import (
    PushEnqueueResult,
    PushJobPublic,
    PushJobsPublic,
    PushRequest,
    PushSkipped,
    RunnerClaimRequest,
    RunnerClaimResponse,
    RunnerJob,
    RunnerReport,
    RunnerStatus,
)
from app.domains.shared.schemas import Message

router = APIRouter(tags=["remote-access-push"])
logger = logging.getLogger(__name__)


def require_runner_token(
    request: Request,
    x_infrascope_runner_token: str | None = Header(default=None),
) -> None:
    """Auth for the runner script. Its own token, or the deploy token when none is set;
    nothing at all when neither is - an unconfigured install must not hand out fleet passwords."""
    expected = (settings.RUSTDESK_RUNNER_TOKEN or settings.RUSTDESK_DEPLOY_TOKEN).strip()
    if not expected:
        raise HTTPException(status_code=503, detail="network push is not configured (RUSTDESK_RUNNER_TOKEN)")
    if not x_infrascope_runner_token or not hmac.compare_digest(x_infrascope_runner_token, expected):
        logger.warning("push runner call with a bad token from %s", _client_ip(request))
        raise HTTPException(status_code=401, detail="invalid runner token")


# --------------------------------------------------------------------------- #
# operators                                                                   #
# --------------------------------------------------------------------------- #
@router.post("/push", response_model=PushEnqueueResult, dependencies=[Depends(get_current_active_superuser)])
def enqueue_push(payload: PushRequest, session: SessionDep, current_user: CurrentUser) -> PushEnqueueResult:
    """Queue RustDesk pushes. Nothing runs here: a runner picks the jobs up."""
    devices = list(session.exec(select(RemoteAccessDevice).where(col(RemoteAccessDevice.id).in_(payload.device_ids))).all())
    found = {d.id for d in devices}
    unknown = [str(i) for i in payload.device_ids if i not in found]
    if unknown:
        raise not_found(f"Devices not found: {', '.join(unknown[:5])}")
    queued, skipped = push_jobs.enqueue_push_jobs(
        session,
        devices,
        profile=payload.profile,
        dry_run=payload.dry_run,
        requested_by=current_user.email,
    )
    return PushEnqueueResult(
        queued=[PushJobPublic.model_validate(j) for j in queued],
        skipped=[PushSkipped(**s) for s in skipped],
    )


@router.get("/push/jobs", response_model=PushJobsPublic, dependencies=[Depends(get_current_active_superuser)])
async def read_push_jobs(session: SessionDep, limit: int = 100) -> PushJobsPublic:
    jobs = push_jobs.list_push_jobs(session, limit=max(1, min(limit, 500)))
    return PushJobsPublic(
        data=[PushJobPublic.model_validate(j) for j in jobs],
        count=len(jobs),
        runner=RunnerStatus(**await push_jobs.runner_status()),
    )


@router.post("/push/jobs/{job_id}/cancel", response_model=Message, dependencies=[Depends(get_current_active_superuser)])
def cancel_push(job_id: uuid.UUID, session: SessionDep) -> Message:
    job = session.get(RemoteAccessPushJob, job_id)
    if not job:
        raise not_found("Push job not found")
    if not push_jobs.cancel_push_job(session, job):
        raise HTTPException(status_code=409, detail="Задание уже выполняется или закрыто, отменить нельзя")
    return Message(message=f"{job.hostname}: задание отменено")


# --------------------------------------------------------------------------- #
# the runner                                                                  #
# --------------------------------------------------------------------------- #
@router.post("/runner/claim", response_model=RunnerClaimResponse, dependencies=[Depends(require_runner_token)])
@limiter.limit("60/minute", key_func=_rate_limit_key)
async def runner_claim(payload: RunnerClaimRequest, session: SessionDep, request: Request) -> RunnerClaimResponse:
    """The runner asks for work. Returns up to `limit` jobs, each with the config to push."""
    _ = request  # required by the rate limiter decorator context
    await push_jobs.note_runner_seen(payload.runner)
    claimed = push_jobs.claim_push_jobs(session, runner=payload.runner, limit=payload.limit)
    return RunnerClaimResponse(
        jobs=[RunnerJob(id=job.id, hostname=job.hostname, profile=job.profile, dry_run=job.dry_run, config=config) for job, config in claimed]
    )


@router.post("/runner/report", response_model=Message, dependencies=[Depends(require_runner_token)])
@limiter.limit("120/minute", key_func=_rate_limit_key)
def runner_report(payload: RunnerReport, session: SessionDep, request: Request) -> Message:
    """The runner says how a job ended; that moves the device's rollout state."""
    _ = request  # required by the rate limiter decorator context
    job = session.get(RemoteAccessPushJob, payload.job_id)
    if not job:
        raise not_found("Push job not found")
    push_jobs.report_push_job(session, job, result=payload.result, detail=payload.detail, os_caption=payload.os_caption)
    return Message(message="ok")
