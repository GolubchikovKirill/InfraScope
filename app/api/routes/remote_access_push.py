"""Network rollout of RustDesk, run by the backend itself over WinRM.

Queueing writes rows (`push_jobs.enqueue_push_jobs`); each queued job is then
handed to the Celery worker (`app.worker.tasks.remote_access_push_job_task`),
which runs it over WinRM (`push_jobs.execute_push_job`). Nothing here blocks on
the actual push - an install can take a few minutes - the route returns as soon
as the jobs are queued and dispatched.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.api.routes._service_errors import not_found
from app.core.config import settings
from app.domains.remote_access import push_jobs
from app.domains.remote_access.models import RemoteAccessDevice, RemoteAccessPushJob
from app.domains.remote_access.schemas import (
    PushEnqueueResult,
    PushJobPublic,
    PushJobsPublic,
    PushRequest,
    PushSkipped,
)
from app.domains.shared.schemas import Message
from app.worker.tasks import remote_access_push_job_task

router = APIRouter(tags=["remote-access-push"], dependencies=[Depends(get_current_active_superuser)])


def _dispatch(jobs: list[RemoteAccessPushJob]) -> None:
    for job in jobs:
        remote_access_push_job_task.apply_async(args=[str(job.id)])


@router.post("/push", response_model=PushEnqueueResult)
def enqueue_push(payload: PushRequest, session: SessionDep, current_user: CurrentUser) -> PushEnqueueResult:
    """Queue RustDesk pushes and dispatch each to the worker right away."""
    if not settings.WINRM_ADMIN_USERNAME or not settings.WINRM_ADMIN_PASSWORD:
        raise HTTPException(status_code=503, detail="network push is not configured (WINRM_ADMIN_USERNAME/WINRM_ADMIN_PASSWORD)")
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
    _dispatch(queued)
    return PushEnqueueResult(
        queued=[PushJobPublic.model_validate(j) for j in queued],
        skipped=[PushSkipped(**s) for s in skipped],
    )


@router.get("/push/jobs", response_model=PushJobsPublic)
async def read_push_jobs(session: SessionDep, limit: int = 100) -> PushJobsPublic:
    jobs = push_jobs.list_push_jobs(session, limit=max(1, min(limit, 500)))
    return PushJobsPublic(
        data=[PushJobPublic.model_validate(j) for j in jobs],
        count=len(jobs),
        configured=bool(settings.WINRM_ADMIN_USERNAME and settings.WINRM_ADMIN_PASSWORD),
    )


@router.post("/push/jobs/{job_id}/cancel", response_model=Message)
def cancel_push(job_id: uuid.UUID, session: SessionDep) -> Message:
    job = session.get(RemoteAccessPushJob, job_id)
    if not job:
        raise not_found("Push job not found")
    if not push_jobs.cancel_push_job(session, job):
        raise HTTPException(status_code=409, detail="Задание уже выполняется или закрыто, отменить нельзя")
    return Message(message=f"{job.hostname}: задание отменено")
