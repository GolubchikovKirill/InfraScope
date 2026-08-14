from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from sqlmodel import func, select

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.core.config import settings
from app.domains.inventory.models import NetworkSwitch
from app.domains.inventory.schemas import (
    DiscoveryResults,
    NetworkSwitchCreate,
    NetworkSwitchesPublic,
    NetworkSwitchPublic,
    NetworkSwitchUpdate,
    ScanProgress,
    ScanRequest,
)
from app.domains.shared.schemas import Message
from app.observability.metrics import set_device_counts
from app.services.cache import get_cached_model, set_cached_model
from app.services.discovery import get_discovery_progress, get_discovery_results, run_discovery_scan
from app.services.event_log import write_event_log
from app.services.internal_services import _proxy_request
from app.services.smart_search import build_ilike_filter

from ._shared import CACHE_TTL, _ensure_unique_switch_ip, _get_switch_or_404, _invalidate_cache

logger = logging.getLogger(__name__)

router = APIRouter(tags=["switches"])


async def _run_switch_discovery(subnet: str, ports: str, known_switches: list[dict]) -> None:
    try:
        await run_discovery_scan("switch", subnet, ports, known_switches)
    except Exception as exc:
        logger.error("Switch discovery failed: %s", exc)


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


@router.post("/discover/scan", response_model=ScanProgress, dependencies=[Depends(get_current_active_superuser)])
async def discover_switch_scan(body: ScanRequest, session: SessionDep) -> dict:
    switches = session.exec(select(NetworkSwitch)).all()
    known = [{"id": str(s.id), "ip_address": s.ip_address, "mac_address": None} for s in switches]
    if settings.DISCOVERY_SERVICE_ENABLED:
        return await _proxy_request(
            base_url=settings.DISCOVERY_SERVICE_URL,
            method="POST",
            path="/discover/switch/scan",
            json_body={
                "subnet": body.subnet,
                "ports": body.ports,
                "known_devices": known,
            },
        )
    asyncio.create_task(_run_switch_discovery(body.subnet, body.ports, known))
    return {"status": "running", "scanned": 0, "total": 0, "found": 0, "message": None}


@router.get("/discover/status", response_model=ScanProgress)
async def discover_switch_status(current_user: CurrentUser) -> dict:
    del current_user
    if settings.DISCOVERY_SERVICE_ENABLED:
        return await _proxy_request(
            base_url=settings.DISCOVERY_SERVICE_URL,
            method="GET",
            path="/discover/switch/status",
        )
    return await get_discovery_progress("switch")


@router.get("/discover/results", response_model=DiscoveryResults)
async def discover_switch_results(current_user: CurrentUser) -> dict:
    del current_user
    if settings.DISCOVERY_SERVICE_ENABLED:
        payload = await _proxy_request(
            base_url=settings.DISCOVERY_SERVICE_URL,
            method="GET",
            path="/discover/switch/results",
        )
        return DiscoveryResults.model_validate(payload).model_dump()
    progress = await get_discovery_progress("switch")
    devices = await get_discovery_results("switch")
    return {"progress": progress, "devices": devices}


@router.post("/discover/add", response_model=NetworkSwitchPublic, dependencies=[Depends(get_current_active_superuser)])
async def discover_add_switch(session: SessionDep, payload: dict) -> NetworkSwitch:
    ip = str(payload.get("ip_address", "")).strip()
    if not ip:
        raise HTTPException(status_code=422, detail="ip_address is required")
    _ensure_unique_switch_ip(session, ip)
    vendor = str(payload.get("vendor") or "generic").strip().lower()
    if vendor not in {"cisco", "dlink", "generic"}:
        vendor = "generic"
    name = str(payload.get("name") or payload.get("hostname") or f"Switch {ip}")[:255]
    switch = NetworkSwitch(
        name=name,
        ip_address=ip,
        vendor=vendor,
        management_protocol="snmp+ssh",
        snmp_version="2c",
        snmp_community_ro="public",
    )
    session.add(switch)
    session.commit()
    session.refresh(switch)
    await _invalidate_cache()
    return switch


@router.post(
    "/discover/update-ip/{switch_id}",
    response_model=NetworkSwitchPublic,
    dependencies=[Depends(get_current_active_superuser)],
)
async def discover_update_switch_ip(
    switch_id: uuid.UUID,
    session: SessionDep,
    new_ip: str = "",
) -> NetworkSwitch:
    switch = _get_switch_or_404(session, switch_id)
    old_ip = switch.ip_address
    if new_ip:
        _ensure_unique_switch_ip(session, new_ip, excluded_switch_id=switch.id)
        switch.ip_address = new_ip
        if old_ip != new_ip:
            write_event_log(
                session,
                category="network",
                event_type="ip_changed",
                severity="warning",
                device_kind="switch",
                device_name=switch.name,
                ip_address=new_ip,
                message=f"Switch '{switch.name}' moved IP: {old_ip} -> {new_ip}",
            )
    switch.updated_at = datetime.now(UTC)
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
