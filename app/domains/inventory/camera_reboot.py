"""PoE power-cycling the cameras behind a store switch.

A camera is any access port on one of CAMERA_VLANS. The whole-store sweep
runs in the worker, not in the request: a store has 20-90 cameras, cycled
one at a time CAMERA_REBOOT_STAGGER_SECONDS apart, then up to
AUTO_REBOOT_AP_VERIFY_MAX_WAIT_SECONDS of waiting for links to return - far
past the proxy's 300 s, so the request used to end in a 504 while the switch
was still being worked through.
"""

from __future__ import annotations

import asyncio
import logging

from sqlmodel import Session

from app.core.config import settings
from app.domains.inventory.models import NetworkSwitch
from app.domains.inventory.switch_write_lock import acquire_switch_write_lease, release_switch_write_lease
from app.services.cisco_ssh import CameraPortInfo, get_camera_ports, poe_cycle_ports_bulk
from app.services.event_log import write_event_log

logger = logging.getLogger(__name__)


def camera_vlans() -> set[int]:
    return {int(v) for v in settings.CAMERA_VLANS.split(",") if v.strip().isdigit()}


def is_empty_port(cam: CameraPortInfo) -> bool:
    """No link and no PoE draw: nothing is plugged in. A hung camera still
    draws power, so a dead link alone does not make a port empty."""
    return cam.oper_status != "connected" and (cam.poe_status or "").lower() != "on"


def read_camera_ports(switch: NetworkSwitch, vlans: set[int]) -> list[CameraPortInfo] | None:
    return get_camera_ports(
        switch.ip_address,
        switch.ssh_username,
        switch.ssh_password,
        switch.enable_password,
        switch.ssh_port,
        vlans,
    )


def poe_cycle_camera_port(switch: NetworkSwitch, port: str) -> bool:
    return poe_cycle_ports_bulk(
        switch.ip_address,
        switch.ssh_username,
        switch.ssh_password,
        switch.enable_password,
        switch.ssh_port,
        [port],
    )


async def verify_camera_ports_back_online(
    switch: NetworkSwitch, ports: list[str], vlans: set[int]
) -> dict[str, bool]:
    """Poll for the given camera ports' link to come back up after a PoE
    cycle - the switch accepting the power-cycle command doesn't mean the
    camera actually reconnected, same reasoning as AP reboot verification.
    """
    max_wait = settings.AUTO_REBOOT_AP_VERIFY_MAX_WAIT_SECONDS
    interval = max(settings.AUTO_REBOOT_AP_VERIFY_POLL_INTERVAL_SECONDS, 1)
    remaining = set(ports)
    back_online: dict[str, bool] = dict.fromkeys(ports, False)
    elapsed = 0
    while elapsed < max_wait and remaining:
        await asyncio.sleep(interval)
        elapsed += interval
        current = await asyncio.to_thread(read_camera_ports, switch, vlans)
        if not current:
            continue
        status_by_port = {c.port: c.oper_status for c in current}
        for p in list(remaining):
            if status_by_port.get(p) == "connected":
                back_online[p] = True
                remaining.discard(p)
    return back_online


async def reboot_all_cameras(session: Session, switch: NetworkSwitch) -> dict:
    """Power-cycle every camera on the switch, one at a time, and report which came back.

    Holds the switch's write lease throughout, like any write from the UI, so
    a single-camera reboot or port change cannot interleave with the sweep.
    """
    vlans = camera_vlans()
    if not vlans:
        return {"status": "no_camera_vlans", "switch": switch.name}

    lease = await acquire_switch_write_lease(switch.id)
    if lease is None:
        return {"status": "busy", "switch": switch.name}
    try:
        ports = await asyncio.to_thread(read_camera_ports, switch, vlans)
        if ports is None:
            return {"status": "unreachable", "switch": switch.name}
        cameras = [cam for cam in ports if not is_empty_port(cam)]
        skipped_empty = len(ports) - len(cameras)
        if not cameras:
            return {"status": "no_cameras", "switch": switch.name, "rebooted_count": 0, "skipped_empty": skipped_empty}

        # One camera at a time, with a pause between each - powering every
        # camera port off at once (even briefly) would drop a store's whole
        # video coverage to zero for that window. Losing one camera while
        # the rest keep recording is a much smaller risk than losing all of
        # them simultaneously.
        stagger = max(settings.CAMERA_REBOOT_STAGGER_SECONDS, 0)
        cycled: list[str] = []
        failed: list[str] = []
        for index, cam in enumerate(cameras):
            ok = await asyncio.to_thread(poe_cycle_camera_port, switch, cam.port)
            (cycled if ok else failed).append(cam.port)
            if index < len(cameras) - 1:
                await asyncio.sleep(stagger)

        back_online = await verify_camera_ports_back_online(switch, cycled, vlans) if cycled else {}
        not_back = [port for port, ok in back_online.items() if not ok]
        result = {
            "status": "done" if cycled else "failed",
            "switch": switch.name,
            "rebooted_count": len(cycled),
            "failed_count": len(failed),
            "back_online_count": len(cycled) - len(not_back),
            "skipped_empty": skipped_empty,
            "failed_ports": failed,
            "not_back_ports": not_back,
        }
    finally:
        await release_switch_write_lease(lease)

    problems = len(failed) + len(not_back)
    write_event_log(
        session,
        category="network",
        event_type="cameras_rebooted",
        severity="warning" if problems else "info",
        device_kind="switch",
        device_name=switch.name,
        ip_address=switch.ip_address,
        message=(
            f"Cameras on '{switch.name}' power-cycled: {result['back_online_count']} of {len(cycled)} back online"
            + (f"; not back: {', '.join(not_back)}" if not_back else "")
            + (f"; cycle failed: {', '.join(failed)}" if failed else "")
        ),
    )
    session.commit()
    logger.info("Camera sweep on %s: %s", switch.name, result)
    return result
