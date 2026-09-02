"""Remote access (self-hosted RustDesk) - status, console passthrough, fleet deploy."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.api.routes._service_errors import not_found
from app.core.config import settings
from app.domains.remote_access import rustdesk_client, service
from app.domains.remote_access.models import RemoteAccessDeployJob, RemoteAccessDevice
from app.domains.remote_access.schemas import (
    AddressBookUpsert,
    AgentHealth,
    AgentJobClaim,
    AgentJobReport,
    AgentJobSecret,
    DeployJobPublic,
    DeployJobsPublic,
    DeployRequest,
    DeviceDesiredUpdate,
    DevicePrepareRequest,
    DevicePrepareResult,
    DevicePublic,
    DevicesPublic,
)
from app.domains.shared.schemas import Message

router = APIRouter(tags=["remote-access"])
logger = logging.getLogger(__name__)


def _to_public(dev: RemoteAccessDevice) -> DevicePublic:
    data = DevicePublic.model_validate(dev)
    data.has_password = bool(dev.permanent_password)
    return data


# --------------------------------------------------------------------------- #
# managed devices                                                            #
# --------------------------------------------------------------------------- #
@router.get("/devices", response_model=DevicesPublic)
def list_devices(
    session: SessionDep,
    current_user: CurrentUser,
    q: str | None = Query(default=None),
    location: str | None = Query(default=None),
    source_kind: str | None = Query(default=None),
    state: str | None = Query(default=None),
    hostnames: str | None = Query(default=None, description="comma-separated exact hostnames"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
) -> DevicesPublic:
    del current_user
    stmt = select(RemoteAccessDevice)
    count_stmt = select(func.count()).select_from(RemoteAccessDevice)
    if hostnames:
        names = [h.strip() for h in hostnames.split(",") if h.strip()]
        if not names:
            return DevicesPublic(data=[], count=0)
        cond = RemoteAccessDevice.hostname.in_(names)  # type: ignore[attr-defined]
        stmt, count_stmt = stmt.where(cond), count_stmt.where(cond)
    if q:
        like = f"%{q.strip()}%"
        cond = RemoteAccessDevice.hostname.ilike(like) | RemoteAccessDevice.rustdesk_id.ilike(like)  # type: ignore[attr-defined]
        stmt, count_stmt = stmt.where(cond), count_stmt.where(cond)
    if location:
        stmt, count_stmt = stmt.where(RemoteAccessDevice.location == location), count_stmt.where(
            RemoteAccessDevice.location == location
        )
    if source_kind:
        stmt, count_stmt = stmt.where(RemoteAccessDevice.source_kind == source_kind), count_stmt.where(
            RemoteAccessDevice.source_kind == source_kind
        )
    if state:
        stmt, count_stmt = stmt.where(RemoteAccessDevice.deploy_state == state), count_stmt.where(
            RemoteAccessDevice.deploy_state == state
        )
    rows = session.exec(stmt.order_by(RemoteAccessDevice.hostname).offset(skip).limit(limit)).all()
    return DevicesPublic(data=[_to_public(r) for r in rows], count=session.exec(count_stmt).one())


@router.patch("/devices/{device_id}", response_model=DevicePublic, dependencies=[Depends(get_current_active_superuser)])
def update_device(device_id: uuid.UUID, payload: DeviceDesiredUpdate, session: SessionDep) -> DevicePublic:
    dev = session.get(RemoteAccessDevice, device_id)
    if not dev:
        raise not_found("Device not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(dev, field, value)
    session.add(dev)
    session.commit()
    session.refresh(dev)
    return _to_public(dev)


@router.post("/devices/{device_id}/rotate-password", response_model=DeployJobPublic,
             dependencies=[Depends(get_current_active_superuser)])
def rotate_password(device_id: uuid.UUID, session: SessionDep, current_user: CurrentUser) -> RemoteAccessDeployJob:
    dev = session.get(RemoteAccessDevice, device_id)
    if not dev:
        raise not_found("Device not found")
    job = service.rotate_password(session, dev, created_by=current_user.email)
    session.commit()
    session.refresh(job)
    return job


@router.post(
    "/devices/prepare",
    response_model=DevicePrepareResult,
    dependencies=[Depends(get_current_active_superuser)],
)
def prepare_device(
    payload: DevicePrepareRequest, session: SessionDep, current_user: CurrentUser
) -> DevicePrepareResult:
    """Install + configure RustDesk on one endpoint, setting its id/password inline."""
    dev, job = service.prepare_device(
        session,
        hostname=payload.hostname,
        rustdesk_id=payload.rustdesk_id,
        permanent_password=payload.permanent_password,
        action=payload.action,
        created_by=current_user.email,
    )
    return DevicePrepareResult(device=_to_public(dev), job=job)


@router.post("/sync", response_model=Message, dependencies=[Depends(get_current_active_superuser)])
async def sync(session: SessionDep) -> Message:
    created = await run_in_threadpool(service.seed_from_inventory, session)
    result = await service.sync_from_console(session) if rustdesk_client.enabled() else {"peers_seen": 0}
    touched = await run_in_threadpool(service.refresh_status_from_inventory, session)
    return Message(
        message=(
            f"seeded {created} devices from inventory, saw {result['peers_seen']} console peers, "
            f"{touched} statuses from InfraScope polling"
        )
    )


# --------------------------------------------------------------------------- #
# fleet deploy                                                               #
# --------------------------------------------------------------------------- #
@router.post("/deploy", response_model=DeployJobsPublic, dependencies=[Depends(get_current_active_superuser)])
def deploy(payload: DeployRequest, session: SessionDep, current_user: CurrentUser) -> DeployJobsPublic:
    devices = service.resolve_scope(
        session,
        device_ids=payload.device_ids,
        location=payload.location,
        source_kind=payload.source_kind,
        all_managed=payload.all_managed,
    )
    if not devices:
        raise HTTPException(status_code=400, detail="deploy scope resolved to no devices")
    jobs = service.enqueue(session, devices, payload.action, created_by=current_user.email)
    return DeployJobsPublic(data=jobs, count=len(jobs))


@router.get("/health", response_model=AgentHealth)
def agent_health(session: SessionDep, current_user: CurrentUser) -> AgentHealth:
    del current_user
    h = service.agent_health(session)
    return AgentHealth(**h, console_ok=rustdesk_client.enabled())


@router.get("/jobs", response_model=DeployJobsPublic)
def list_jobs(
    session: SessionDep,
    current_user: CurrentUser,
    status: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
) -> DeployJobsPublic:
    del current_user
    stmt = select(RemoteAccessDeployJob)
    count_stmt = select(func.count()).select_from(RemoteAccessDeployJob)
    if status:
        stmt, count_stmt = stmt.where(RemoteAccessDeployJob.status == status), count_stmt.where(
            RemoteAccessDeployJob.status == status
        )
    rows = session.exec(stmt.order_by(RemoteAccessDeployJob.created_at.desc()).offset(skip).limit(limit)).all()  # type: ignore[attr-defined]
    return DeployJobsPublic(data=rows, count=session.exec(count_stmt).one())


# --------------------------------------------------------------------------- #
# console passthrough (InfraScope auth in front of the RustDesk console)     #
# --------------------------------------------------------------------------- #
@router.get("/console/connections")
async def console_connections(current_user: CurrentUser, limit: int = Query(default=200, ge=1, le=1000)) -> list[dict]:
    del current_user
    return await rustdesk_client.list_connections(limit=limit)


@router.get("/console/users")
async def console_users(current_user: CurrentUser) -> list[dict]:
    del current_user
    return await rustdesk_client.list_users()


@router.get("/console/address-book")
async def console_address_book(current_user: CurrentUser) -> list[dict]:
    del current_user
    return await rustdesk_client.get_address_book()


@router.post("/console/address-book", response_model=Message,
             dependencies=[Depends(get_current_active_superuser)])
async def console_address_book_upsert(payload: AddressBookUpsert) -> Message:
    await rustdesk_client.upsert_address_book_entry(payload.model_dump())
    return Message(message="address-book entry saved")


@router.delete("/console/address-book/{peer_id}", response_model=Message,
               dependencies=[Depends(get_current_active_superuser)])
async def console_address_book_delete(peer_id: str) -> Message:
    await rustdesk_client.delete_address_book_entry(peer_id)
    return Message(message="address-book entry deleted")


# --------------------------------------------------------------------------- #
# Windows deploy-agent endpoints (shared-token auth, not user auth)          #
# --------------------------------------------------------------------------- #
def _verify_agent(x_deploy_agent_token: str | None = Header(default=None)) -> None:
    expected = settings.RUSTDESK_DEPLOY_AGENT_TOKEN.strip()
    if not expected:
        raise HTTPException(status_code=503, detail="deploy agent is not configured (RUSTDESK_DEPLOY_AGENT_TOKEN)")
    if x_deploy_agent_token != expected:
        raise HTTPException(status_code=401, detail="invalid deploy agent token")


agent_router = APIRouter(prefix="/agent", tags=["remote-access-agent"], dependencies=[Depends(_verify_agent)])


@agent_router.post("/claim", response_model=AgentJobClaim | None)
def agent_claim(session: SessionDep, agent_id: str = Query(min_length=1, max_length=128)) -> AgentJobClaim | None:
    job = service.claim_next_job(session, agent_id)
    if not job:
        return None
    dev = session.get(RemoteAccessDevice, job.device_id)
    return AgentJobClaim(
        job_id=job.id,
        device_id=job.device_id,
        hostname=job.hostname,
        action=job.action,
        params=job.params,
        rustdesk_id=dev.rustdesk_id if dev else None,
        id_server=settings.RUSTDESK_ID_SERVER,
        relay_server=settings.RUSTDESK_RELAY_SERVER,
        key=settings.RUSTDESK_KEY,
        installer_version=settings.RUSTDESK_INSTALLER_VERSION,
        desired_hidden=dev.desired_hidden if dev else True,
        desired_block_outgoing=dev.desired_block_outgoing if dev else True,
        desired_unattended=dev.desired_unattended if dev else True,
    )


@agent_router.get("/jobs/{job_id}/secret", response_model=AgentJobSecret)
def agent_job_secret(job_id: uuid.UUID, session: SessionDep) -> AgentJobSecret:
    job = session.get(RemoteAccessDeployJob, job_id)
    if not job:
        raise not_found("Job not found")
    return AgentJobSecret(permanent_password=service.job_secret(session, job))


@agent_router.post("/jobs/{job_id}/report", response_model=Message)
def agent_job_report(job_id: uuid.UUID, payload: AgentJobReport, session: SessionDep) -> Message:
    job = session.get(RemoteAccessDeployJob, job_id)
    if not job:
        raise not_found("Job not found")
    service.report_job(
        session,
        job,
        status=payload.status,
        detail=payload.detail,
        facts={
            "installed_version": payload.installed_version,
            "rustdesk_id": payload.rustdesk_id,
            "deploy_state": payload.deploy_state,
        },
    )
    return Message(message="ok")


router.include_router(agent_router)
