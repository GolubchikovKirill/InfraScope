from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.api.routes._service_errors import not_found
from app.core.config import settings
from app.domains.inventory.ap_registry import (
    get_known_aps,
    known_aps_as_still_responding,
    merge_live_and_known,
    record_seen_aps,
    set_ap_excluded,
)
from app.domains.inventory.schemas import AccessPointInfo, CameraPortInfo, SetApExcludedRequest
from app.domains.shared.schemas import Message
from app.observability.metrics import switch_ops_total
from app.services.cisco_ssh import get_access_points, get_camera_ports, poe_cycle_ap, poe_cycle_ports_bulk, reboot_ap
from app.services.internal_services import _proxy_request

from ._shared import (
    _acquire_switch_write_lock,
    _enforce_switch_cooldown,
    _get_switch_or_404,
    _release_switch_write_lock,
    _validate_switch_port,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["switches"])


@router.get("/{switch_id}/access-points", response_model=list[AccessPointInfo])
async def get_switch_aps(
    switch_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> list[AccessPointInfo]:
    switch = _get_switch_or_404(session, switch_id)
    if switch.vendor != "cisco":
        raise HTTPException(status_code=400, detail="Access point discovery is available for Cisco switches")

    live_aps = await asyncio.to_thread(
        get_access_points,
        switch.ip_address,
        switch.ssh_username,
        switch.ssh_password,
        switch.enable_password,
        switch.ssh_port,
        switch.ap_vlan,
    )
    known_rows = get_known_aps(session, switch_id=switch.id)

    if live_aps is None:
        # Couldn't reach the switch this time - show the known APs as still
        # responding rather than flagging them hung on a missed scan alone.
        logger.warning("Could not scan %s for access points (SSH unreachable); showing last-known state", switch.name)
        merged = known_aps_as_still_responding(known_rows, vlan=switch.ap_vlan)
    else:
        live_aps = [ap for ap in live_aps if ap.mac_address and ap.port]
        record_seen_aps(session, switch_id=switch.id, live_aps=live_aps)
        merged = merge_live_and_known(live_aps, known_rows, vlan=switch.ap_vlan)

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
            is_responding=ap.is_responding,
            last_seen_at=ap.last_seen_at,
            exclude_from_auto_reboot=ap.exclude_from_auto_reboot,
        )
        for ap in merged
    ]


@router.get("/{switch_id}/camera-ports", response_model=list[CameraPortInfo])
async def get_switch_camera_ports(
    switch_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> list[CameraPortInfo]:
    switch = _get_switch_or_404(session, switch_id)
    if switch.vendor != "cisco":
        raise HTTPException(status_code=400, detail="Camera port lookup is available for Cisco switches")

    camera_vlans = {int(v) for v in settings.CAMERA_VLANS.split(",") if v.strip().isdigit()}
    if not camera_vlans:
        return []

    ports = await asyncio.to_thread(
        get_camera_ports,
        switch.ip_address,
        switch.ssh_username,
        switch.ssh_password,
        switch.enable_password,
        switch.ssh_port,
        camera_vlans,
    )
    if ports is None:
        raise HTTPException(status_code=503, detail="Could not reach switch via SSH")

    return [
        CameraPortInfo(
            port=p.port,
            vlan=p.vlan,
            oper_status=p.oper_status,
            description=p.description,
            poe_power=p.poe_power,
            poe_status=p.poe_status,
        )
        for p in ports
    ]


@router.post("/{switch_id}/camera-ports/reboot-all", dependencies=[Depends(get_current_active_superuser)])
async def reboot_all_camera_ports(switch_id: uuid.UUID, session: SessionDep) -> dict:
    switch = _get_switch_or_404(session, switch_id)
    if switch.vendor != "cisco":
        raise HTTPException(status_code=400, detail="Camera reboot is available for Cisco switches")

    camera_vlans = {int(v) for v in settings.CAMERA_VLANS.split(",") if v.strip().isdigit()}
    if not camera_vlans:
        raise HTTPException(status_code=400, detail="No camera VLANs configured")

    lock_key = await _acquire_switch_write_lock(switch_id)
    await _enforce_switch_cooldown(switch_id=switch_id, port="*", operation="reboot_cameras_bulk")
    try:
        ports = await asyncio.to_thread(
            get_camera_ports,
            switch.ip_address,
            switch.ssh_username,
            switch.ssh_password,
            switch.enable_password,
            switch.ssh_port,
            camera_vlans,
        )
        if ports is None:
            raise HTTPException(status_code=503, detail="Could not reach switch via SSH")
        if not ports:
            return {"status": "no_cameras", "rebooted_count": 0}

        ok = await asyncio.to_thread(
            poe_cycle_ports_bulk,
            switch.ip_address,
            switch.ssh_username,
            switch.ssh_password,
            switch.enable_password,
            switch.ssh_port,
            [p.port for p in ports],
        )
        if not ok:
            switch_ops_total.labels(operation="reboot_cameras_bulk", result="error").inc()
            raise HTTPException(status_code=502, detail="Failed to reboot camera ports")
        switch_ops_total.labels(operation="reboot_cameras_bulk", result="success").inc()
        return {"status": "rebooting", "rebooted_count": len(ports)}
    finally:
        await _release_switch_write_lock(lock_key)


@router.patch("/{switch_id}/access-points/{mac_address}/exclude", dependencies=[Depends(get_current_active_superuser)])
async def set_switch_ap_excluded(
    switch_id: uuid.UUID,
    mac_address: str,
    payload: SetApExcludedRequest,
    session: SessionDep,
) -> Message:
    _get_switch_or_404(session, switch_id)
    found = set_ap_excluded(session, switch_id=switch_id, mac_address=mac_address, excluded=payload.excluded)
    if not found:
        raise not_found("Access point not found in registry for this switch")
    return Message(
        message="Excluded from auto-reboot" if payload.excluded else "Included in auto-reboot"
    )


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
