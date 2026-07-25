from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.domains.inventory.models import SwitchPortSnapshot
from app.domains.inventory.schemas import (
    SwitchPortAdminStateUpdate,
    SwitchPortDescriptionUpdate,
    SwitchPortInfo,
    SwitchPortModeUpdate,
    SwitchPortPoeUpdate,
    SwitchPortSnapshotEntry,
    SwitchPortSnapshotHistory,
    SwitchPortsPublic,
    SwitchPortVlanUpdate,
)
from app.domains.shared.schemas import Message
from app.observability.metrics import switch_port_op_duration_seconds, switch_port_ops_total
from app.services.cache import get_cached_model, set_cached_model
from app.services.internal_services import _proxy_request
from app.services.smart_search import text_matches_query
from app.services.switches import resolve_switch_provider

from ._shared import (
    _acquire_switch_write_lock,
    _enforce_switch_cooldown,
    _get_switch_or_404,
    _invalidate_ports_cache,
    _release_switch_write_lock,
    _require_superuser,
    _validate_switch_port,
)

router = APIRouter(tags=["switches"])


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


@router.get("/{switch_id}/port-config-history", response_model=SwitchPortSnapshotHistory)
async def get_switch_port_config_history(
    switch_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    limit: int = Query(default=20, ge=1, le=100),
) -> SwitchPortSnapshotHistory:
    _get_switch_or_404(session, switch_id)
    rows = session.exec(
        select(SwitchPortSnapshot)
        .where(SwitchPortSnapshot.switch_id == switch_id)
        .order_by(SwitchPortSnapshot.captured_at.desc())
        .limit(limit)
    ).all()
    return SwitchPortSnapshotHistory(
        data=[
            SwitchPortSnapshotEntry(
                id=row.id,
                captured_at=row.captured_at,
                port_count=len(row.ports_json),
            )
            for row in rows
        ],
        count=len(rows),
    )


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
