import asyncio
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.api.routes._service_errors import conflict, not_found
from app.domains.inventory.computer_polling import (
    invalidate_computer_cache,
    poll_all_computers_local,
    probe_computer,
)
from app.domains.inventory.models import Computer
from app.domains.inventory.schemas import ComputerCreate, ComputerPublic, ComputersPublic, ComputerUpdate
from app.domains.shared.schemas import Message
from app.services.cache import get_cached_model, set_cached_model
from app.services.smart_search import build_ilike_filter

router = APIRouter(tags=["computers"])

logger = logging.getLogger(__name__)

CACHE_TTL = 30


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
) -> tuple[list[Computer], int]:
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
) -> ComputersPublic:
    del current_user
    cache_key = f"computers:{q or ''}:{skip}:{limit}"
    if cached := await get_cached_model(cache_key, ComputersPublic):
        return cached

    rows, count = await run_in_threadpool(_query_computers_page, session, q, skip, limit)
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


@router.delete("/{computer_id}", dependencies=[Depends(get_current_active_superuser)])
async def delete_computer(session: SessionDep, computer_id: uuid.UUID) -> Message:
    row = _get_computer_or_404(session, computer_id)
    session.delete(row)
    session.commit()
    await invalidate_computer_cache()
    return Message(message="Computer deleted")


@router.post("/{computer_id}/poll", response_model=ComputerPublic)
async def poll_computer(computer_id: uuid.UUID, session: SessionDep, current_user: CurrentUser) -> Computer:
    del current_user
    row = _get_computer_or_404(session, computer_id)
    is_online, reason = await asyncio.to_thread(probe_computer, row.hostname)
    row.is_online = is_online
    row.reachability_reason = reason
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
