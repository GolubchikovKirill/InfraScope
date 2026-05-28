import asyncio
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.api.routes._service_errors import conflict, not_found
from app.core.config import settings
from app.core.redis import get_redis
from app.domains.inventory.models import Computer
from app.domains.inventory.reachability import probe_host_ports
from app.domains.inventory.schemas import ComputerCreate, ComputerPublic, ComputersPublic, ComputerUpdate
from app.domains.shared.schemas import Message
from app.services.cache import get_cached_model, invalidate_entity_cache, set_cached_model
from app.services.smart_search import build_ilike_filter

router = APIRouter(tags=["computers"])

logger = logging.getLogger(__name__)

CACHE_TTL = 30


async def _invalidate_cache() -> None:
    await invalidate_entity_cache("computers")


_COMPUTER_PROBE_PORTS = (445, 3389, 135)


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


def _probe_computer(hostname: str) -> tuple[bool, str | None]:
    result = probe_host_ports(
        hostname,
        ports=_COMPUTER_PROBE_PORTS,
        timeout=1.2,
        dns_search_suffixes=settings.DNS_SEARCH_SUFFIXES,
        dns_server=settings.DNS_SERVER,
    )
    return result.is_online, result.reason


async def _probe_computers_bulk(rows: list[Computer]) -> dict[uuid.UUID, tuple[bool, str | None]]:
    semaphore = asyncio.Semaphore(max(1, settings.COMPUTER_POLL_CONCURRENCY))

    async def _run(row: Computer) -> tuple[uuid.UUID, tuple[bool, str | None]]:
        async with semaphore:
            return row.id, await asyncio.to_thread(_probe_computer, row.hostname)

    pairs = await asyncio.gather(*[_run(row) for row in rows]) if rows else []
    return dict(pairs)


@router.get("/", response_model=ComputersPublic)
async def read_computers(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    q: str | None = Query(default=None),
) -> ComputersPublic:
    del current_user
    cache_key = f"computers:{q or ''}:{skip}:{limit}"
    if cached := await get_cached_model(cache_key, ComputersPublic):
        return cached

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
    result = ComputersPublic(data=rows, count=count)

    await set_cached_model(cache_key, result, ttl=CACHE_TTL)

    return result


@router.post("/", response_model=ComputerPublic, dependencies=[Depends(get_current_active_superuser)])
async def create_computer(session: SessionDep, payload: ComputerCreate) -> Computer:
    _ensure_unique_hostname(session, payload.hostname)
    row = Computer(**payload.model_dump())
    session.add(row)
    session.commit()
    session.refresh(row)
    await _invalidate_cache()
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
    await _invalidate_cache()
    return row


@router.delete("/{computer_id}", dependencies=[Depends(get_current_active_superuser)])
async def delete_computer(session: SessionDep, computer_id: uuid.UUID) -> Message:
    row = _get_computer_or_404(session, computer_id)
    session.delete(row)
    session.commit()
    await _invalidate_cache()
    return Message(message="Computer deleted")


@router.post("/{computer_id}/poll", response_model=ComputerPublic)
async def poll_computer(computer_id: uuid.UUID, session: SessionDep, current_user: CurrentUser) -> Computer:
    del current_user
    row = _get_computer_or_404(session, computer_id)
    is_online, reason = await asyncio.to_thread(_probe_computer, row.hostname)
    row.is_online = is_online
    row.reachability_reason = reason
    row.last_polled_at = datetime.now(UTC)
    session.add(row)
    session.commit()
    session.refresh(row)
    await _invalidate_cache()
    return row


@router.post("/poll-all", response_model=ComputersPublic)
async def poll_all_computers(session: SessionDep, current_user: CurrentUser) -> ComputersPublic:
    del current_user
    lock_key = "lock:poll-all:computers"
    lock_acquired = True
    try:
        redis = await get_redis()
        lock_acquired = bool(await redis.set(lock_key, "1", ex=45, nx=True))
    except Exception:
        lock_acquired = True

    rows = session.exec(select(Computer)).all()
    if not lock_acquired:
        logger.info("Skipping duplicate poll-all request for computers: lock busy")
        return ComputersPublic(data=rows, count=len(rows))

    try:
        probe_results = await _probe_computers_bulk(rows)
        now = datetime.now(UTC)
        for row in rows:
            is_online, reason = probe_results.get(row.id, (False, "probe_failed"))
            row.is_online = is_online
            row.reachability_reason = reason
            row.last_polled_at = now
            session.add(row)
        session.commit()
        await _invalidate_cache()
        return ComputersPublic(data=rows, count=len(rows))
    finally:
        if lock_acquired:
            try:
                redis = await get_redis()
                await redis.delete(lock_key)
            except Exception:
                pass
