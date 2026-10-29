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
from app.domains.inventory.camera_reboot import camera_vlans, is_empty_port, verify_camera_ports_back_online
from app.domains.inventory.schemas import AccessPointInfo, CameraPortInfo, SetApExcludedRequest
from app.domains.inventory.switch_write_lock import switch_write_lease_held
from app.domains.shared.schemas import Message
from app.observability.metrics import switch_ops_total
from app.services.cisco_ssh import get_access_points, get_camera_ports, poe_cycle_ap, poe_cycle_ports_bulk, reboot_ap
from app.services.event_log import write_event_log
from app.worker.tasks import camera_reboot_all_task

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
            consecutive_reboot_failures=ap.consecutive_reboot_failures,
            consecutive_no_power_skips=ap.consecutive_no_power_skips,
            needs_attention_since=ap.needs_attention_since,
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

    vlans = camera_vlans()
    if not vlans:
        return []

    ports = await asyncio.to_thread(
        get_camera_ports,
        switch.ip_address,
        switch.ssh_username,
        switch.ssh_password,
        switch.enable_password,
        switch.ssh_port,
        vlans,
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
            empty=is_empty_port(p),
        )
        for p in ports
    ]


@router.post("/{switch_id}/camera-ports/{port:path}/reboot", dependencies=[Depends(get_current_active_superuser)])
async def reboot_camera_port(switch_id: uuid.UUID, port: str, session: SessionDep) -> dict:
    safe_port = _validate_switch_port(port)
    switch = _get_switch_or_404(session, switch_id)
    if switch.vendor != "cisco":
        raise HTTPException(status_code=400, detail="Camera reboot is available for Cisco switches")

    vlans = camera_vlans()
    if not vlans:
        raise HTTPException(status_code=400, detail="No camera VLANs configured")

    lock_key = await _acquire_switch_write_lock(switch_id)
    try:
        # Inside the try: a 429 from here used to skip the release, and the
        # lease's renewal task then kept the switch locked (409 on every
        # write) until the backend restarted.
        await _enforce_switch_cooldown(switch_id=switch_id, port=safe_port, operation="reboot_camera")
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
        back_online_map = await verify_camera_ports_back_online(switch, [safe_port], vlans)
        return {"status": "rebooting", "port": safe_port, "back_online": back_online_map.get(safe_port, False)}
    finally:
        await _release_switch_write_lock(lock_key)


@router.post("/{switch_id}/camera-ports/reboot-all", dependencies=[Depends(get_current_active_superuser)])
async def reboot_all_camera_ports(switch_id: uuid.UUID, session: SessionDep) -> dict:
    """Queue the whole-store sweep; the worker runs it (see camera_reboot) and
    the UI follows it through /tasks/{task_id}."""
    switch = _get_switch_or_404(session, switch_id)
    if switch.vendor != "cisco":
        raise HTTPException(status_code=400, detail="Camera reboot is available for Cisco switches")
    if not camera_vlans():
        raise HTTPException(status_code=400, detail="No camera VLANs configured")
    if await switch_write_lease_held(switch_id):
        raise HTTPException(status_code=409, detail="Another switch write operation is already running")
    await _enforce_switch_cooldown(switch_id=switch_id, port="*", operation="reboot_cameras_bulk")

    task = camera_reboot_all_task.apply_async(args=[str(switch_id)])
    switch_ops_total.labels(operation="reboot_cameras_bulk", result="queued").inc()
    return {"status": "queued", "task_id": task.id}


@router.patch("/{switch_id}/access-points/{mac_address}/exclude", dependencies=[Depends(get_current_active_superuser)])
def set_switch_ap_excluded(
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


# Superuser-only, like every other endpoint here that power-cycles hardware
# (camera-ports/reboot, camera-ports/reboot-all). The UI has always hidden
# this button from non-superusers, but the endpoint itself accepted any
# authenticated session - so the restriction only ever existed in the
# browser, and a PoE cycle on a live AP was one API call away for any user.
@router.post("/{switch_id}/reboot-ap", dependencies=[Depends(get_current_active_superuser)])
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
    try:
        await _enforce_switch_cooldown(switch_id=switch_id, port=interface, operation=f"reboot_ap_{method}")
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
