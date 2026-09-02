"""Remote access (self-hosted RustDesk) - status, console passthrough, address book.

The client is rolled out through Kaspersky Security Center with a preconfigured
package (see docs/rustdesk-ksc-deployment.md). InfraScope tracks and administers;
it does not push the client.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.api.routes._service_errors import not_found
from app.domains.remote_access import rustdesk_client, service
from app.domains.remote_access.models import RemoteAccessDevice
from app.domains.remote_access.schemas import (
    AddressBookSyncRequest,
    AddressBookUpsert,
    DeviceDesiredUpdate,
    DeviceEnsureRequest,
    DevicePublic,
    DevicesPublic,
    PackageConfig,
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


@router.post(
    "/devices/ensure", response_model=DevicePublic, dependencies=[Depends(get_current_active_superuser)]
)
def ensure_device(payload: DeviceEnsureRequest, session: SessionDep) -> DevicePublic:
    dev = service.ensure_device(
        session,
        hostname=payload.hostname,
        rustdesk_id=payload.rustdesk_id,
        permanent_password=payload.permanent_password,
    )
    return _to_public(dev)


@router.post(
    "/devices/{device_id}/rotate-password",
    response_model=DevicePublic,
    dependencies=[Depends(get_current_active_superuser)],
)
def rotate_password(device_id: uuid.UUID, session: SessionDep) -> DevicePublic:
    dev = session.get(RemoteAccessDevice, device_id)
    if not dev:
        raise not_found("Device not found")
    dev = service.rotate_password(session, dev)
    return _to_public(dev)


@router.get(
    "/devices/{device_id}/package",
    response_model=PackageConfig,
    dependencies=[Depends(get_current_active_superuser)],
)
def device_package(device_id: uuid.UUID, session: SessionDep) -> PackageConfig:
    """Config the KSC post-install step needs for this machine."""
    dev = session.get(RemoteAccessDevice, device_id)
    if not dev:
        raise not_found("Device not found")
    return PackageConfig(**service.package_config(dev))


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
# console passthrough (InfraScope auth in front of the RustDesk console)     #
# --------------------------------------------------------------------------- #
@router.post("/address-book/sync", response_model=Message, dependencies=[Depends(get_current_active_superuser)])
async def address_book_sync(payload: AddressBookSyncRequest, session: SessionDep) -> Message:
    devices = service.resolve_scope(
        session,
        device_ids=payload.device_ids,
        location=payload.location,
        source_kind=payload.source_kind,
        all_managed=payload.device_ids is None,
    )
    if not devices:
        raise HTTPException(status_code=400, detail="address-book sync scope resolved to no devices")
    res = await service.push_address_book(session, devices)
    return Message(message=f"address book: {res['pushed']} pushed, {res['failed']} failed")


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
