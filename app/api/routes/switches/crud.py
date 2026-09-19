from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool
from sqlmodel import func, select

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.domains.inventory.models import NetworkSwitch
from app.domains.inventory.schemas import (
    NetworkSwitchCreate,
    NetworkSwitchesPublic,
    NetworkSwitchPublic,
    NetworkSwitchUpdate,
)
from app.domains.shared.schemas import Message
from app.observability.metrics import set_device_counts
from app.services.cache import get_cached_model, set_cached_model
from app.services.event_log import write_event_log
from app.services.smart_search import build_ilike_filter

from ._shared import CACHE_TTL, _ensure_unique_switch_ip, _get_switch_or_404, _invalidate_cache

logger = logging.getLogger(__name__)

router = APIRouter(tags=["switches"])


def _query_switches_page(
    session: SessionDep,
    name: str | None,
    skip: int,
    limit: int,
) -> tuple[list[NetworkSwitch], int]:
    statement = select(NetworkSwitch)
    count_stmt = select(func.count()).select_from(NetworkSwitch)
    if name:
        flt = build_ilike_filter(
            [
                NetworkSwitch.name,
                NetworkSwitch.hostname,
                NetworkSwitch.ip_address,
                NetworkSwitch.model_info,
                NetworkSwitch.ios_version,
                NetworkSwitch.vendor,
            ],
            name,
        )
        if flt is not None:
            statement = statement.where(flt)
            count_stmt = count_stmt.where(flt)
    count = session.exec(count_stmt).one()
    switches = session.exec(statement.offset(skip).limit(limit).order_by(NetworkSwitch.name)).all()
    return switches, count


@router.get("/", response_model=NetworkSwitchesPublic)
async def read_switches(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, le=200),
    name: str | None = None,
) -> NetworkSwitchesPublic:
    cache_key = f"switches:{name or ''}:{skip}:{limit}"
    if cached := await get_cached_model(cache_key, NetworkSwitchesPublic):
        return cached

    switches, count = await run_in_threadpool(_query_switches_page, session, name, skip, limit)
    set_device_counts(
        kind="switch",
        total=len(switches),
        online=sum(1 for s in switches if s.is_online),
    )
    result = NetworkSwitchesPublic(data=switches, count=count)

    await set_cached_model(cache_key, result, ttl=CACHE_TTL)

    return result


@router.post("/", response_model=NetworkSwitchPublic, dependencies=[Depends(get_current_active_superuser)])
async def create_switch(session: SessionDep, switch_in: NetworkSwitchCreate) -> NetworkSwitch:
    _ensure_unique_switch_ip(session, switch_in.ip_address, conflict_status_code=400)
    switch = NetworkSwitch(**switch_in.model_dump())
    session.add(switch)
    session.commit()
    session.refresh(switch)
    await _invalidate_cache()
    return switch


@router.get("/{switch_id}", response_model=NetworkSwitchPublic)
def read_switch(switch_id: uuid.UUID, session: SessionDep, current_user: CurrentUser) -> NetworkSwitch:
    return _get_switch_or_404(session, switch_id)


@router.patch("/{switch_id}", response_model=NetworkSwitchPublic, dependencies=[Depends(get_current_active_superuser)])
async def update_switch(
    session: SessionDep,
    switch_id: uuid.UUID,
    switch_in: NetworkSwitchUpdate,
    current_user: CurrentUser,
) -> NetworkSwitch:
    switch = _get_switch_or_404(session, switch_id)
    update_data = switch_in.model_dump(exclude_unset=True)
    if "ip_address" in update_data and update_data["ip_address"] is not None:
        _ensure_unique_switch_ip(session, update_data["ip_address"], excluded_switch_id=switch_id)
    auto_reboot_was_disabled = (
        update_data.get("auto_reboot_aps_enabled") is False and switch.auto_reboot_aps_enabled
    )
    switch.updated_at = datetime.now(UTC)
    switch.sqlmodel_update(update_data)
    if auto_reboot_was_disabled:
        # Historical warnings stay available via the event log, but the
        # current-state counters must no longer describe a disabled feature.
        switch.consecutive_unreachable_cycles = 0
        switch.consecutive_no_aps_found_cycles = 0
        switch.switch_needs_attention_since = None
        write_event_log(
            session,
            severity="info",
            category="network",
            event_type="ap_auto_reboot_disabled",
            device_kind="switch",
            device_name=switch.name,
            ip_address=switch.ip_address,
            message=f"{current_user.email}: disabled automatic AP reboot for {switch.name}",
        )
    session.add(switch)
    session.commit()
    session.refresh(switch)
    await _invalidate_cache()
    return switch


@router.delete("/{switch_id}", dependencies=[Depends(get_current_active_superuser)])
async def delete_switch(session: SessionDep, switch_id: uuid.UUID) -> Message:
    switch = _get_switch_or_404(session, switch_id)
    session.delete(switch)
    session.commit()
    await _invalidate_cache()
    return Message(message="Switch deleted")
