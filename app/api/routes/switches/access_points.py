from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.api.routes._service_errors import not_found
from app.core.config import settings
from app.domains.inventory.ap_auto_reboot import _verify_ap_back_online
from app.domains.inventory.ap_registry import (
    get_known_aps,
    known_aps_as_still_responding,
    merge_live_and_known,
    record_seen_aps,
    recover_missing_macs_from_registry,
    set_ap_excluded,
)
from app.domains.inventory.models import NetworkSwitch
from app.domains.inventory.schemas import AccessPointInfo, CameraPortInfo, SetApExcludedRequest
from app.domains.shared.schemas import Message
from app.observability.metrics import switch_ops_total
from app.services.cisco_ssh import get_access_points, get_camera_ports, poe_cycle_ap, poe_cycle_ports_bulk, reboot_ap
from app.services.event_log import write_event_log
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
        live_aps = recover_missing_macs_from_registry(live_aps, known_rows)
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


async def _verify_camera_ports_back_online(
    switch: NetworkSwitch, ports: list[str], camera_vlans: set[int]
) -> dict[str, bool]:
    """Poll for the given camera ports' link to come back up after a PoE
    cycle - the switch accepting the power-cycle command doesn't mean the
    camera actually reconnected, same reasoning as AP reboot verification.
    """
    max_wait = settings.AUTO_REBOOT_AP_VERIFY_MAX_WAIT_SECONDS
    interval = max(settings.AUTO_REBOOT_AP_VERIFY_POLL_INTERVAL_SECONDS, 1)
    remaining = set(ports)
    back_online: dict[str, bool] = {p: False for p in ports}
    elapsed = 0
    while elapsed < max_wait and remaining:
        await asyncio.sleep(interval)
        elapsed += interval
        current = await asyncio.to_thread(
            get_camera_ports,
            switch.ip_address,
            switch.ssh_username,
            switch.ssh_password,
            switch.enable_password,
            switch.ssh_port,
            camera_vlans,
        )
        if not current:
            continue
        status_by_port = {c.port: c.oper_status for c in current}
        for p in list(remaining):
            if status_by_port.get(p) == "connected":
                back_online[p] = True
                remaining.discard(p)
    return back_online


@router.post("/{switch_id}/camera-ports/{port:path}/reboot", dependencies=[Depends(get_current_active_superuser)])
async def reboot_camera_port(switch_id: uuid.UUID, port: str, session: SessionDep) -> dict:
    safe_port = _validate_switch_port(port)
    switch = _get_switch_or_404(session, switch_id)
    if switch.vendor != "cisco":
        raise HTTPException(status_code=400, detail="Camera reboot is available for Cisco switches")

    camera_vlans = {int(v) for v in settings.CAMERA_VLANS.split(",") if v.strip().isdigit()}
    if not camera_vlans:
        raise HTTPException(status_code=400, detail="No camera VLANs configured")

    lock_key = await _acquire_switch_write_lock(switch_id)
    await _enforce_switch_cooldown(switch_id=switch_id, port=safe_port, operation="reboot_camera")
    try:
        ok = await asyncio.to_thread(
            poe_cycle_ports_bulk,
            switch.ip_address,
            switch.ssh_username,
            switch.ssh_password,
            switch.enable_password,
            switch.ssh_port,
            [safe_port],
        )
        if not ok:
            switch_ops_total.labels(operation="reboot_camera", result="error").inc()
            raise HTTPException(status_code=502, detail="Failed to reboot camera port")
        switch_ops_total.labels(operation="reboot_camera", result="success").inc()
        back_online_map = await _verify_camera_ports_back_online(switch, [safe_port], camera_vlans)
        return {"status": "rebooting", "port": safe_port, "back_online": back_online_map.get(safe_port, False)}
    finally:
        await _release_switch_write_lock(lock_key)


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

        # One camera at a time, with a pause between each - powering every
        # camera port off at once (even briefly) would drop a store's whole
        # video coverage to zero for that window. Losing one camera while
        # the rest keep recording is a much smaller risk than losing all of
        # them simultaneously.
        stagger = max(settings.CAMERA_REBOOT_STAGGER_SECONDS, 0)
        cycled_ports: list[str] = []
        failed_ports: list[str] = []
        for index, cam in enumerate(ports):
            ok = await asyncio.to_thread(
                poe_cycle_ports_bulk,
                switch.ip_address,
                switch.ssh_username,
                switch.ssh_password,
                switch.enable_password,
                switch.ssh_port,
                [cam.port],
            )
            (cycled_ports if ok else failed_ports).append(cam.port)
            if index < len(ports) - 1:
                await asyncio.sleep(stagger)

        if not cycled_ports:
            switch_ops_total.labels(operation="reboot_cameras_bulk", result="error").inc()
            raise HTTPException(status_code=502, detail="Failed to reboot any camera port")
        switch_ops_total.labels(operation="reboot_cameras_bulk", result="success").inc()
        if failed_ports:
            switch_ops_total.labels(operation="reboot_cameras_bulk", result="partial").inc()

        back_online_map = await _verify_camera_ports_back_online(switch, cycled_ports, camera_vlans)
        back_online_count = sum(1 for v in back_online_map.values() if v)
        return {
            "status": "rebooting",
            "rebooted_count": len(cycled_ports),
            "failed_count": len(failed_ports),
            "back_online_count": back_online_count,
        }
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
    raw_mac = payload.get("mac_address")
    mac_address = str(raw_mac).strip() if raw_mac else None

    switch = _get_switch_or_404(session, switch_id)
    if switch.vendor != "cisco":
        raise HTTPException(status_code=400, detail="AP reboot is available for Cisco switches")

    lock_key = await _acquire_switch_write_lock(switch_id)
    await _enforce_switch_cooldown(switch_id=switch_id, port=interface, operation=f"reboot_ap_{method}")
    try:
        if settings.NETWORK_CONTROL_SERVICE_ENABLED:
            result = await _proxy_request(
                base_url=settings.NETWORK_CONTROL_SERVICE_URL,
                method="POST",
                path=f"/switches/{switch_id}/reboot-ap",
                json_body={"interface": interface, "method": method},
            )
        else:
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
            result = {"status": "rebooting", "interface": interface, "method": method}

        # The power-cycle command succeeding only means the switch accepted
        # it, not that the AP actually came back - same verify-by-polling the
        # scheduled auto-reboot cycle already does, so a manual reboot can't
        # silently report "done" on an AP that never returned (this is
        # exactly the class of miss that hid VN3's failed recovery earlier).
        if mac_address:
            back_online = await _verify_ap_back_online(switch, mac_address)
            result = {**result, "back_online": back_online}
            write_event_log(
                session,
                severity="info" if back_online else "error",
                category="network",
                event_type="ap_auto_reboot" if back_online else "ap_auto_reboot_failed",
                device_kind="switch",
                device_name=switch.name,
                ip_address=switch.ip_address,
                message=(
                    f"Manual reboot ({current_user.email}): AP {mac_address} (port {interface}) on {switch.name} "
                    + ("came back online" if back_online else f"did not reappear within {settings.AUTO_REBOOT_AP_VERIFY_MAX_WAIT_SECONDS}s")
                ),
            )
            session.commit()
        return result
    finally:
        await _release_switch_write_lock(lock_key)
