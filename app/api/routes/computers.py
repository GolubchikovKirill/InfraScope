import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, Depends, Query, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.api.routes._service_errors import conflict, not_found
from app.core.config import settings
from app.domains.inventory.computer_polling import (
    invalidate_computer_cache,
    poll_all_computers_local,
    probe_computer,
)
from app.domains.inventory.computer_stale import find_stale_computers
from app.domains.inventory.models import Computer
from app.domains.inventory.network_discovery import discover_and_probe
from app.domains.inventory.schemas import (
    ComputerCreate,
    ComputerPublic,
    ComputersPublic,
    ComputerUpdate,
    DnsDiscoveryPublic,
    StaleComputerPublic,
    StaleComputersPublic,
)
from app.domains.remote_access import service as remote_access_service
from app.domains.shared.schemas import Message
from app.services.cache import EntityCache
from app.services.smart_search import build_ilike_filter

router = APIRouter(tags=["computers"])

logger = logging.getLogger(__name__)

CACHE_TTL = 30
_COMPUTERS_CACHE = EntityCache("computers", ttl=CACHE_TTL)


def _get_computer_or_404(session: SessionDep, computer_id: uuid.UUID) -> Computer:
    row = session.get(Computer, computer_id)
    if not row:
        raise not_found("Computer not found")
    return row


def _ensure_unique_hostname(
    session: SessionDep,
    hostname: str,
    *,
    excluded_computer_id: uuid.UUID | None = None,
) -> None:
    filters = [Computer.hostname == hostname]
    if excluded_computer_id is not None:
        filters.append(Computer.id != excluded_computer_id)
    exists = session.exec(select(Computer).where(*filters)).first()
    if exists:
        raise conflict("Computer with this hostname already exists")


def _query_computers_page(
    session: SessionDep,
    q: str | None,
    skip: int,
    limit: int,
) -> tuple[Sequence[Computer], int]:
    statement = select(Computer)
    count_stmt = select(func.count()).select_from(Computer)
    if q:
        flt = build_ilike_filter(
            [Computer.hostname, Computer.location, Computer.comment],
            q,
        )
        if flt is not None:
            statement = statement.where(flt)
            count_stmt = count_stmt.where(flt)
    rows = session.exec(statement.order_by(Computer.hostname).offset(skip).limit(limit)).all()
    count = session.exec(count_stmt).one()
    return rows, count


@router.get("/", response_model=ComputersPublic)
async def read_computers(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    q: str | None = Query(default=None),
) -> Response:
    del current_user
    cache_variant = f"{q or ''}:{skip}:{limit}"
    if cached := await _COMPUTERS_CACHE.get_response(cache_variant):
        return cached

    rows, count = await run_in_threadpool(_query_computers_page, session, q, skip, limit)
    result = ComputersPublic(data=cast(list[ComputerPublic], list(rows)), count=count)

    return await _COMPUTERS_CACHE.respond(cache_variant, result)


@router.post("/", response_model=ComputerPublic, dependencies=[Depends(get_current_active_superuser)])
async def create_computer(session: SessionDep, payload: ComputerCreate) -> Computer:
    _ensure_unique_hostname(session, payload.hostname)
    row = Computer(**payload.model_dump())
    session.add(row)
    session.commit()
    session.refresh(row)
    await invalidate_computer_cache()
    return row


@router.patch("/{computer_id}", response_model=ComputerPublic, dependencies=[Depends(get_current_active_superuser)])
async def update_computer(session: SessionDep, computer_id: uuid.UUID, payload: ComputerUpdate) -> Computer:
    row = _get_computer_or_404(session, computer_id)
    updates = payload.model_dump(exclude_unset=True)
    new_hostname = updates.get("hostname")
    if new_hostname and new_hostname != row.hostname:
        _ensure_unique_hostname(session, new_hostname, excluded_computer_id=computer_id)
    row.sqlmodel_update(updates)
    row.updated_at = datetime.now(UTC)
    session.add(row)
    session.commit()
    session.refresh(row)
    await invalidate_computer_cache()
    return row


@router.post("/discover", response_model=DnsDiscoveryPublic, dependencies=[Depends(get_current_active_superuser)])
async def discover_computers(session: SessionDep) -> DnsDiscoveryPublic:
    """Add the machines of a discovered role (DNS_DISCOVERY_ROLES, the store
    screens) that DNS knows and the inventory does not. The worker does the same
    every hour; this is the "find on the network" button on the screens page."""
    result = await discover_and_probe(session)
    if result.added and settings.REMOTE_ACCESS_ENABLED:
        # straight into remote access too, rather than on the next 2-minute sync
        await run_in_threadpool(remote_access_service.seed_from_inventory, session)
        await run_in_threadpool(remote_access_service.refresh_status_from_inventory, session)
    return DnsDiscoveryPublic(zone=result.zone, seen=result.seen, matched=result.matched, added=result.added)


@router.get("/stale", response_model=StaleComputersPublic, dependencies=[Depends(get_current_active_superuser)])
async def read_stale_computers(session: SessionDep) -> StaleComputersPublic:
    """Computers that are not in the RustDesk console and do not answer a ping - leftovers
    of the AD import. Only reports; removal is the ordinary DELETE, one computer at a time."""
    report = await find_stale_computers(session)
    data = [
        StaleComputerPublic(
            id=item.computer.id,
            hostname=item.computer.hostname,
            location=item.computer.location,
            comment=item.computer.comment,
            is_online=item.computer.is_online,
            last_polled_at=item.computer.last_polled_at,
            created_at=item.computer.created_at,
            reason=item.reason,
            laptop_like=item.laptop_like,
            in_remote_access=item.in_remote_access,
        )
        for item in report.items
    ]
    return StaleComputersPublic(console_reachable=report.console_reachable, count=len(data), data=data)


@router.delete("/{computer_id}", dependencies=[Depends(get_current_active_superuser)])
async def delete_computer(session: SessionDep, computer_id: uuid.UUID) -> Message:
    row = _get_computer_or_404(session, computer_id)
    await remote_access_service.release_inventory_row(session, computer_id=row.id)
    session.delete(row)
    session.commit()
    await invalidate_computer_cache()
    return Message(message="Computer deleted")


@router.post("/{computer_id}/poll", response_model=ComputerPublic)
async def poll_computer(computer_id: uuid.UUID, session: SessionDep, current_user: CurrentUser) -> Computer:
    del current_user
    row = _get_computer_or_404(session, computer_id)
    probe = await probe_computer(row.hostname)
    row.is_online = probe.is_online
    row.reachability_reason = probe.reason
    row.last_polled_at = datetime.now(UTC)
    session.add(row)
    session.commit()
    session.refresh(row)
    await invalidate_computer_cache()
    return row


@router.post("/poll-all", response_model=ComputersPublic)
async def poll_all_computers(session: SessionDep, current_user: CurrentUser) -> ComputersPublic:
    del current_user
    return await poll_all_computers_local(session=session)
