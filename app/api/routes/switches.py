import asyncio
import logging
import re
import uuid
from datetime import UTC, datetime
from time import monotonic

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from sqlmodel import func, select

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.api.routes._service_errors import conflict, not_found
from app.core.config import settings
from app.core.redis import get_redis
from app.domains.inventory.models import NetworkSwitch
from app.domains.inventory.schemas import (
    AccessPointInfo,
    DiscoveryResults,
    NetworkSwitchCreate,
    NetworkSwitchesPublic,
    NetworkSwitchPublic,
    NetworkSwitchUpdate,
    ScanProgress,
    ScanRequest,
    SwitchPortAdminStateUpdate,
    SwitchPortDescriptionUpdate,
    SwitchPortInfo,
    SwitchPortModeUpdate,
    SwitchPortPoeUpdate,
    SwitchPortsPublic,
    SwitchPortVlanUpdate,
)
from app.domains.inventory.switch_polling import (
    SwitchNotFoundError,
    poll_all_switches_local,
    poll_single_switch_local,
)
from app.domains.shared.schemas import Message
from app.observability.metrics import (
    set_device_counts,
    switch_ops_total,
    switch_port_op_duration_seconds,
    switch_port_ops_total,
)
from app.services.cache import get_cached_model, invalidate_entity_cache, set_cached_model
from app.services.cisco_ssh import get_access_points, poe_cycle_ap, reboot_ap
from app.services.discovery import get_discovery_progress, get_discovery_results, run_discovery_scan
from app.services.event_log import write_event_log
from app.services.internal_services import _proxy_request
from app.services.smart_search import build_ilike_filter, text_matches_query
from app.services.switches import resolve_switch_provider

logger = logging.getLogger(__name__)

router = APIRouter(tags=["switches"])
_local_safety_mutex = asyncio.Lock()
_local_switch_write_locks: dict[str, float] = {}
_local_switch_cooldowns: dict[str, float] = {}
_SAFE_PORT_PATTERN = re.compile(
    r"^(?:"
    r"Gi|GigabitEthernet|"
    r"Fa|FastEthernet|"
    r"Te|TenGigabitEthernet|"
    r"Twe|TwentyFiveGigE|"
    r"Po|Port-channel"
    r")\d+(?:/\d+){0,3}$",
    re.IGNORECASE,
)


def _validate_switch_port(port: str) -> str:
    value = port.strip()
    if not value or len(value) > 64:
        raise HTTPException(status_code=422, detail="Invalid switch port identifier")
    if not _SAFE_PORT_PATTERN.match(value):
        raise HTTPException(status_code=422, detail="Unsafe or unsupported switch port format")
    return value


async def _acquire_switch_write_lock(switch_id: uuid.UUID) -> str | None:
    lock_key = f"lock:switch-write:{switch_id}"
    try:
        r = await asyncio.wait_for(get_redis(), timeout=0.2)
        locked = await asyncio.wait_for(
            r.set(lock_key, "1", ex=settings.SWITCH_WRITE_LOCK_SECONDS, nx=True),
            timeout=0.3,
        )
        if not locked:
            raise HTTPException(status_code=409, detail="Another switch write operation is already running")
        return lock_key
    except HTTPException:
        raise
    except Exception:
        expires_at = monotonic() + max(int(settings.SWITCH_WRITE_LOCK_SECONDS), 1)
        async with _local_safety_mutex:
            existing = _local_switch_write_locks.get(lock_key)
            if existing and existing > monotonic():
                raise HTTPException(status_code=409, detail="Another switch write operation is already running")
            _local_switch_write_locks[lock_key] = expires_at
        return f"local:{lock_key}"


async def _release_switch_write_lock(lock_key: str | None) -> None:
    if not lock_key:
        return
    if lock_key.startswith("local:"):
        raw_key = lock_key.removeprefix("local:")
        async with _local_safety_mutex:
            _local_switch_write_locks.pop(raw_key, None)
        return
    try:
        r = await asyncio.wait_for(get_redis(), timeout=0.2)
        await asyncio.wait_for(r.delete(lock_key), timeout=0.3)
    except Exception:
        pass


async def _enforce_switch_cooldown(*, switch_id: uuid.UUID, port: str, operation: str) -> None:
    cooldown = max(int(settings.SWITCH_SAFETY_COOLDOWN_SECONDS), 0)
    if cooldown == 0:
        return
    cooldown_key = f"cooldown:switch-write:{switch_id}:{operation}:{port}"
    try:
        r = await asyncio.wait_for(get_redis(), timeout=0.2)
        ok = await asyncio.wait_for(r.set(cooldown_key, "1", ex=cooldown, nx=True), timeout=0.3)
        if not ok:
            raise HTTPException(
                status_code=429,
                detail=f"Operation throttled by safety cooldown ({cooldown}s). Try again later.",
            )
    except HTTPException:
        raise
    except Exception:
        now = monotonic()
        async with _local_safety_mutex:
            existing = _local_switch_cooldowns.get(cooldown_key)
            if existing and existing > now:
                raise HTTPException(
                    status_code=429,
                    detail=f"Operation throttled by safety cooldown ({cooldown}s). Try again later.",
                )
            _local_switch_cooldowns[cooldown_key] = now + cooldown


async def _run_switch_discovery(subnet: str, ports: str, known_switches: list[dict]) -> None:
    try:
        await run_discovery_scan("switch", subnet, ports, known_switches)
    except Exception as exc:
        logger.error("Switch discovery failed: %s", exc)


CACHE_TTL = 30


def _get_switch_or_404(session: SessionDep, switch_id: uuid.UUID) -> NetworkSwitch:
    switch = session.get(NetworkSwitch, switch_id)
    if not switch:
        raise not_found("Switch not found")
    return switch


def _ensure_unique_switch_ip(
    session: SessionDep,
    ip_address: str,
    *,
    excluded_switch_id: uuid.UUID | None = None,
    conflict_status_code: int = 409,
) -> None:
    filters = [NetworkSwitch.ip_address == ip_address]
    if excluded_switch_id is not None:
        filters.append(NetworkSwitch.id != excluded_switch_id)
    existing = session.exec(select(NetworkSwitch).where(*filters)).first()
    if existing:
        raise conflict("Switch with this IP already exists", status_code=conflict_status_code)


async def _invalidate_cache() -> None:
    await invalidate_entity_cache("switches")


async def _invalidate_ports_cache(switch_id: uuid.UUID) -> None:
    await invalidate_entity_cache(f"switch_ports:{switch_id}")


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
async def update_switch(session: SessionDep, switch_id: uuid.UUID, switch_in: NetworkSwitchUpdate) -> NetworkSwitch:
    switch = _get_switch_or_404(session, switch_id)
    update_data = switch_in.model_dump(exclude_unset=True)
    if "ip_address" in update_data and update_data["ip_address"] is not None:
        _ensure_unique_switch_ip(session, update_data["ip_address"], excluded_switch_id=switch_id)
    switch.updated_at = datetime.now(UTC)
    switch.sqlmodel_update(update_data)
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


@router.post("/{switch_id}/poll", response_model=NetworkSwitchPublic)
async def poll_switch(
    switch_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> NetworkSwitch | NetworkSwitchPublic:
    del current_user
    if settings.POLLING_SERVICE_ENABLED:
        payload = await _proxy_request(
            base_url=settings.POLLING_SERVICE_URL,
            method="POST",
            path=f"/poll/switches/{switch_id}",
        )
        return NetworkSwitchPublic.model_validate(payload)

    try:
        return await poll_single_switch_local(session=session, switch_id=switch_id)
    except SwitchNotFoundError:
        raise HTTPException(status_code=404, detail="Switch not found")


@router.post("/poll-all", response_model=Message)
async def poll_all_switches(
    session: SessionDep,
    current_user: CurrentUser,
) -> Message:
    del current_user
    if settings.POLLING_SERVICE_ENABLED:
        payload = await _proxy_request(
            base_url=settings.POLLING_SERVICE_URL,
            method="POST",
            path="/poll/switches",
        )
        return Message.model_validate(payload)

    return await poll_all_switches_local(session=session)


@router.get("/{switch_id}/access-points", response_model=list[AccessPointInfo])
async def get_switch_aps(
    switch_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> list[AccessPointInfo]:
    switch = _get_switch_or_404(session, switch_id)
    if switch.vendor != "cisco":
        raise HTTPException(status_code=400, detail="Access point discovery is available for Cisco switches")

    aps = await asyncio.to_thread(
        get_access_points,
        switch.ip_address,
        switch.ssh_username,
        switch.ssh_password,
        switch.enable_password,
        switch.ssh_port,
        switch.ap_vlan,
    )
    switch_ops_total.labels(operation="access_points", result="success").inc()

    return [
        AccessPointInfo(
            mac_address=ap.mac_address,
            port=ap.port,
            vlan=ap.vlan,
            ip_address=ap.ip_address,
            cdp_name=ap.cdp_name,
            cdp_platform=ap.cdp_platform,
            poe_power=ap.poe_power,
            poe_status=ap.poe_status,
        )
        for ap in aps
    ]


@router.post("/{switch_id}/reboot-ap")
async def reboot_access_point(
    switch_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    payload: dict,
) -> dict:
    interface = _validate_switch_port(str(payload.get("interface", "")))
    method = str(payload.get("method", "poe")).strip().lower()
    if method not in {"poe", "shutdown"}:
        raise HTTPException(status_code=422, detail="method must be 'poe' or 'shutdown'")
    lock_key = await _acquire_switch_write_lock(switch_id)
    await _enforce_switch_cooldown(switch_id=switch_id, port=interface, operation=f"reboot_ap_{method}")

    if settings.NETWORK_CONTROL_SERVICE_ENABLED:
        try:
            return await _proxy_request(
                base_url=settings.NETWORK_CONTROL_SERVICE_URL,
                method="POST",
                path=f"/switches/{switch_id}/reboot-ap",
                json_body={"interface": interface, "method": method},
            )
        finally:
            await _release_switch_write_lock(lock_key)
    try:
        switch = _get_switch_or_404(session, switch_id)
        if switch.vendor != "cisco":
            raise HTTPException(status_code=400, detail="AP reboot is available for Cisco switches")

        if method == "poe":
            ok = await asyncio.to_thread(
                poe_cycle_ap,
                switch.ip_address,
                switch.ssh_username,
                switch.ssh_password,
                switch.enable_password,
                switch.ssh_port,
                interface,
            )
        else:
            ok = await asyncio.to_thread(
                reboot_ap,
                switch.ip_address,
                switch.ssh_username,
                switch.ssh_password,
                switch.enable_password,
                switch.ssh_port,
                interface,
            )

        if not ok:
            switch_ops_total.labels(operation="reboot_ap", result="error").inc()
            raise HTTPException(status_code=502, detail="Failed to reboot AP")
        switch_ops_total.labels(operation="reboot_ap", result="success").inc()
        return {"status": "rebooting", "interface": interface, "method": method}
    finally:
        await _release_switch_write_lock(lock_key)


@router.get("/{switch_id}/ports", response_model=SwitchPortsPublic)
async def get_switch_ports(
    switch_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    q: str | None = Query(default=None),
) -> SwitchPortsPublic:
    cache_key = f"switch_ports:{switch_id}:{q or ''}:{skip}:{limit}"
    if cached := await get_cached_model(cache_key, SwitchPortsPublic):
        return cached

    switch = _get_switch_or_404(session, switch_id)
    provider = resolve_switch_provider(switch)
    operation = "get_ports"
    vendor = switch.vendor
    with switch_port_op_duration_seconds.labels(vendor=vendor, operation=operation).time():
        try:
            ports = await asyncio.to_thread(provider.get_ports, switch)
            switch_port_ops_total.labels(vendor=vendor, operation=operation, result="success").inc()
        except Exception as exc:
            switch_port_ops_total.labels(vendor=vendor, operation=operation, result="error").inc()
            raise HTTPException(status_code=502, detail=f"Failed to fetch switch ports: {exc}") from exc
    if q:
        ports = [
            p
            for p in ports
            if text_matches_query(
                [
                    p.port,
                    p.description,
                    p.status_text,
                    p.vlan_text,
                    p.media_type,
                ],
                q,
            )
        ]
    window = ports[skip : skip + limit]
    data = [
        SwitchPortInfo(
            port=p.port,
            if_index=p.if_index,
            description=p.description,
            admin_status=p.admin_status,
            oper_status=p.oper_status,
            status_text=p.status_text,
            vlan_text=p.vlan_text,
            duplex_text=p.duplex_text,
            speed_text=p.speed_text,
            media_type=p.media_type,
            speed_mbps=p.speed_mbps,
            duplex=p.duplex,
            vlan=p.vlan,
            port_mode=p.port_mode,
            access_vlan=p.access_vlan,
            trunk_native_vlan=p.trunk_native_vlan,
            trunk_allowed_vlans=p.trunk_allowed_vlans,
            poe_enabled=p.poe_enabled,
            poe_power_w=p.poe_power_w,
            mac_count=p.mac_count,
        )
        for p in window
    ]
    result = SwitchPortsPublic(data=data, count=len(ports))
    await set_cached_model(cache_key, result, ttl=20)
    return result


def _require_superuser(current_user: CurrentUser) -> None:
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Only superusers can perform write operations")


async def _run_port_write(
    *,
    session: SessionDep,
    switch_id: uuid.UUID,
    current_user: CurrentUser,
    operation: str,
    port: str,
    callback,
) -> Message:
    _require_superuser(current_user)
    safe_port = _validate_switch_port(port)
    switch = _get_switch_or_404(session, switch_id)
    lock_key = await _acquire_switch_write_lock(switch_id)
    if operation in {"admin_state", "vlan", "poe", "mode"}:
        await _enforce_switch_cooldown(switch_id=switch_id, port=safe_port, operation=operation)
    provider = resolve_switch_provider(switch)
    vendor = switch.vendor
    try:
        with switch_port_op_duration_seconds.labels(vendor=vendor, operation=operation).time():
            try:
                await asyncio.to_thread(callback, switch, provider, safe_port)
                switch_port_ops_total.labels(vendor=vendor, operation=operation, result="success").inc()
            except Exception as exc:
                switch_port_ops_total.labels(vendor=vendor, operation=operation, result="error").inc()
                raise HTTPException(status_code=502, detail=f"Port operation failed: {exc}") from exc
        await _invalidate_ports_cache(switch_id)
        return Message(message="ok")
    finally:
        await _release_switch_write_lock(lock_key)


@router.post("/{switch_id}/ports/{port:path}/admin-state", response_model=Message)
async def set_port_admin_state(
    switch_id: uuid.UUID,
    port: str,
    body: SwitchPortAdminStateUpdate,
    session: SessionDep,
    current_user: CurrentUser,
) -> Message:
    safe_port = _validate_switch_port(port)
    if settings.NETWORK_CONTROL_SERVICE_ENABLED:
        _require_superuser(current_user)
        lock_key = await _acquire_switch_write_lock(switch_id)
        await _enforce_switch_cooldown(switch_id=switch_id, port=safe_port, operation="admin_state")
        try:
            payload = await _proxy_request(
                base_url=settings.NETWORK_CONTROL_SERVICE_URL,
                method="POST",
                path=f"/switches/{switch_id}/ports/{safe_port}/admin-state",
                json_body={"admin_state": body.admin_state},
            )
            await _invalidate_ports_cache(switch_id)
            return Message.model_validate(payload)
        finally:
            await _release_switch_write_lock(lock_key)
    return await _run_port_write(
        session=session,
        switch_id=switch_id,
        current_user=current_user,
        operation="admin_state",
        port=safe_port,
        callback=lambda sw, provider, p: provider.set_admin_state(sw, p, body.admin_state),
    )


@router.post("/{switch_id}/ports/{port:path}/description", response_model=Message)
async def set_port_description(
    switch_id: uuid.UUID,
    port: str,
    body: SwitchPortDescriptionUpdate,
    session: SessionDep,
    current_user: CurrentUser,
) -> Message:
    safe_port = _validate_switch_port(port)
    if settings.NETWORK_CONTROL_SERVICE_ENABLED:
        _require_superuser(current_user)
        lock_key = await _acquire_switch_write_lock(switch_id)
        try:
            payload = await _proxy_request(
                base_url=settings.NETWORK_CONTROL_SERVICE_URL,
                method="POST",
                path=f"/switches/{switch_id}/ports/{safe_port}/description",
                json_body={"description": body.description},
            )
            await _invalidate_ports_cache(switch_id)
            return Message.model_validate(payload)
        finally:
            await _release_switch_write_lock(lock_key)
    return await _run_port_write(
        session=session,
        switch_id=switch_id,
        current_user=current_user,
        operation="description",
        port=safe_port,
        callback=lambda sw, provider, p: provider.set_description(sw, p, body.description),
    )


@router.post("/{switch_id}/ports/{port:path}/vlan", response_model=Message)
async def set_port_vlan(
    switch_id: uuid.UUID,
    port: str,
    body: SwitchPortVlanUpdate,
    session: SessionDep,
    current_user: CurrentUser,
) -> Message:
    safe_port = _validate_switch_port(port)
    if settings.NETWORK_CONTROL_SERVICE_ENABLED:
        _require_superuser(current_user)
        lock_key = await _acquire_switch_write_lock(switch_id)
        await _enforce_switch_cooldown(switch_id=switch_id, port=safe_port, operation="vlan")
        try:
            payload = await _proxy_request(
                base_url=settings.NETWORK_CONTROL_SERVICE_URL,
                method="POST",
                path=f"/switches/{switch_id}/ports/{safe_port}/vlan",
                json_body={"vlan": body.vlan},
            )
            await _invalidate_ports_cache(switch_id)
            return Message.model_validate(payload)
        finally:
            await _release_switch_write_lock(lock_key)
    return await _run_port_write(
        session=session,
        switch_id=switch_id,
        current_user=current_user,
        operation="vlan",
        port=safe_port,
        callback=lambda sw, provider, p: provider.set_vlan(sw, p, body.vlan),
    )


@router.post("/{switch_id}/ports/{port:path}/poe", response_model=Message)
async def set_port_poe(
    switch_id: uuid.UUID,
    port: str,
    body: SwitchPortPoeUpdate,
    session: SessionDep,
    current_user: CurrentUser,
) -> Message:
    safe_port = _validate_switch_port(port)
    if settings.NETWORK_CONTROL_SERVICE_ENABLED:
        _require_superuser(current_user)
        lock_key = await _acquire_switch_write_lock(switch_id)
        await _enforce_switch_cooldown(switch_id=switch_id, port=safe_port, operation="poe")
        try:
            payload = await _proxy_request(
                base_url=settings.NETWORK_CONTROL_SERVICE_URL,
                method="POST",
                path=f"/switches/{switch_id}/ports/{safe_port}/poe",
                json_body={"action": body.action},
            )
            await _invalidate_ports_cache(switch_id)
            return Message.model_validate(payload)
        finally:
            await _release_switch_write_lock(lock_key)
    return await _run_port_write(
        session=session,
        switch_id=switch_id,
        current_user=current_user,
        operation="poe",
        port=safe_port,
        callback=lambda sw, provider, p: provider.set_poe(sw, p, body.action),
    )


@router.post("/{switch_id}/ports/{port:path}/mode", response_model=Message)
async def set_port_mode(
    switch_id: uuid.UUID,
    port: str,
    body: SwitchPortModeUpdate,
    session: SessionDep,
    current_user: CurrentUser,
) -> Message:
    safe_port = _validate_switch_port(port)
    if settings.NETWORK_CONTROL_SERVICE_ENABLED:
        _require_superuser(current_user)
        lock_key = await _acquire_switch_write_lock(switch_id)
        await _enforce_switch_cooldown(switch_id=switch_id, port=safe_port, operation="mode")
        try:
            payload = await _proxy_request(
                base_url=settings.NETWORK_CONTROL_SERVICE_URL,
                method="POST",
                path=f"/switches/{switch_id}/ports/{safe_port}/mode",
                json_body={
                    "mode": body.mode,
                    "access_vlan": body.access_vlan,
                    "native_vlan": body.native_vlan,
                    "allowed_vlans": body.allowed_vlans,
                },
            )
            await _invalidate_ports_cache(switch_id)
            return Message.model_validate(payload)
        finally:
            await _release_switch_write_lock(lock_key)
    return await _run_port_write(
        session=session,
        switch_id=switch_id,
        current_user=current_user,
        operation="mode",
        port=safe_port,
        callback=lambda sw, provider, p: provider.set_mode(
            sw,
            p,
            body.mode,
            access_vlan=body.access_vlan,
            native_vlan=body.native_vlan,
            allowed_vlans=body.allowed_vlans,
        ),
    )
