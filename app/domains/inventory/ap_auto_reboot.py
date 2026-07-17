"""Scheduled Wi-Fi access point reboot, restricted to VLAN 20.

This is a live-hardware pilot: a switch's own `auto_reboot_aps_enabled`
toggle is necessary but not sufficient. The store must ALSO be present in
`settings.AUTO_REBOOT_AP_ALLOWED_STORES`, and `ap_vlan` must be exactly 20.
Both gates exist so an accidental toggle elsewhere can't reboot APs it
shouldn't - the allowlist is the one that matters and is not editable from
the UI, only via a settings/redeploy change once a store has been verified.

Each AP is rebooted one at a time, with a pause and an online-check between
them, so a whole store's Wi-Fi never drops at once. `auto_reboot_mode`
defaults to "dry_run": it discovers and logs what it would do without
touching the hardware, so the schedule/discovery can be verified for a few
days before a store is switched to "live".
"""

from __future__ import annotations

import asyncio
import logging

from sqlmodel import Session, select

from app.core.config import settings
from app.domains.inventory.models import NetworkSwitch
from app.services.cisco_ssh import APInfo, get_access_points, poe_cycle_ap
from app.services.event_log import write_event_log

logger = logging.getLogger(__name__)

REQUIRED_AP_VLAN = 20


def _parse_allowed_stores(raw: str) -> set[str]:
    return {_normalize_store_name(s) for s in raw.split(",") if s.strip()}


def _normalize_store_name(name: str) -> str:
    # Store codes are inconsistently typed in Cyrillic vs Latin (e.g. "А12"
    # vs "A1"), so map Cyrillic look-alike letters to their Latin equivalent
    # before comparing against the allowlist.
    cyrillic_to_latin = str.maketrans("АВЕКМНОРСТХаес", "ABEKMHOPCTXaec")
    return name.strip().upper().translate(cyrillic_to_latin)


async def _verify_ap_back_online(switch: NetworkSwitch, ap: APInfo) -> bool:
    aps = await asyncio.to_thread(
        get_access_points,
        switch.ip_address,
        switch.ssh_username,
        switch.ssh_password,
        switch.enable_password,
        switch.ssh_port,
        switch.ap_vlan,
    )
    return any(candidate.mac_address == ap.mac_address for candidate in aps)


async def _reboot_switch_aps(session: Session, switch: NetworkSwitch) -> dict:
    is_dry_run = switch.auto_reboot_mode != "live"
    mode_label = "dry_run" if is_dry_run else "live"

    aps = await asyncio.to_thread(
        get_access_points,
        switch.ip_address,
        switch.ssh_username,
        switch.ssh_password,
        switch.enable_password,
        switch.ssh_port,
        switch.ap_vlan,
    )
    aps = [ap for ap in aps if ap.port][: settings.AUTO_REBOOT_AP_MAX_PER_SWITCH]

    if not aps:
        write_event_log(
            session,
            severity="info",
            category="network",
            event_type="ap_auto_reboot_skipped",
            device_kind="switch",
            device_name=switch.name,
            ip_address=switch.ip_address,
            message=f"Auto-reboot ({mode_label}): no VLAN {switch.ap_vlan} access points found on {switch.name}",
        )
        session.commit()
        return {"switch": switch.name, "mode": mode_label, "aps_found": 0, "results": []}

    results: list[dict] = []
    for ap in aps:
        if is_dry_run:
            write_event_log(
                session,
                severity="info",
                category="network",
                event_type="ap_auto_reboot_dry_run",
                device_kind="switch",
                device_name=switch.name,
                ip_address=switch.ip_address,
                message=(
                    f"[DRY RUN] Would PoE-cycle AP {ap.mac_address} (port {ap.port}) "
                    f"on {switch.name}, VLAN {switch.ap_vlan}"
                ),
            )
            results.append({"port": ap.port, "mac_address": ap.mac_address, "action": "dry_run"})
            continue

        ok = await asyncio.to_thread(
            poe_cycle_ap,
            switch.ip_address,
            switch.ssh_username,
            switch.ssh_password,
            switch.enable_password,
            switch.ssh_port,
            ap.port,
        )
        write_event_log(
            session,
            severity="info" if ok else "error",
            category="network",
            event_type="ap_auto_reboot",
            device_kind="switch",
            device_name=switch.name,
            ip_address=switch.ip_address,
            message=(
                f"Auto-reboot: PoE-cycled AP {ap.mac_address} (port {ap.port}) on {switch.name}: "
                f"{'ok' if ok else 'command failed'}"
            ),
        )
        session.commit()

        came_back = False
        if ok:
            await asyncio.sleep(settings.AUTO_REBOOT_AP_PAUSE_SECONDS)
            came_back = await _verify_ap_back_online(switch, ap)
            if not came_back:
                write_event_log(
                    session,
                    severity="error",
                    category="network",
                    event_type="ap_auto_reboot_failed",
                    device_kind="switch",
                    device_name=switch.name,
                    ip_address=switch.ip_address,
                    message=(
                        f"AP {ap.mac_address} (port {ap.port}) on {switch.name} did not reappear "
                        f"on VLAN {switch.ap_vlan} after reboot"
                    ),
                )
                session.commit()

        results.append(
            {"port": ap.port, "mac_address": ap.mac_address, "action": "rebooted", "ok": ok, "back_online": came_back}
        )

    return {"switch": switch.name, "mode": mode_label, "aps_found": len(aps), "results": results}


async def run_scheduled_ap_reboot_cycle(*, session: Session) -> dict:
    if not settings.AUTO_REBOOT_AP_ENABLED:
        logger.info("Auto-reboot cycle skipped: AUTO_REBOOT_AP_ENABLED is false")
        return {"status": "disabled"}

    allowed_stores = _parse_allowed_stores(settings.AUTO_REBOOT_AP_ALLOWED_STORES)
    if not allowed_stores:
        logger.info("Auto-reboot cycle skipped: AUTO_REBOOT_AP_ALLOWED_STORES is empty")
        return {"status": "no_allowed_stores"}

    switches = session.exec(select(NetworkSwitch).where(NetworkSwitch.auto_reboot_aps_enabled)).all()

    switch_results = []
    for switch in switches:
        if switch.vendor != "cisco":
            logger.info("Auto-reboot skipped for %s: vendor %s not supported", switch.name, switch.vendor)
            continue
        if switch.ap_vlan != REQUIRED_AP_VLAN:
            logger.warning(
                "Auto-reboot skipped for %s: ap_vlan=%s (only VLAN %s is allowed)",
                switch.name,
                switch.ap_vlan,
                REQUIRED_AP_VLAN,
            )
            continue
        if _normalize_store_name(switch.name) not in allowed_stores:
            logger.info(
                "Auto-reboot skipped for %s: store not in AUTO_REBOOT_AP_ALLOWED_STORES allowlist", switch.name
            )
            continue

        try:
            switch_results.append(await _reboot_switch_aps(session, switch))
        except Exception as exc:
            logger.exception("Auto-reboot cycle failed for switch %s", switch.name)
            write_event_log(
                session,
                severity="error",
                category="network",
                event_type="ap_auto_reboot_error",
                device_kind="switch",
                device_name=switch.name,
                ip_address=switch.ip_address,
                message=f"Auto-reboot cycle raised an error on {switch.name}: {exc}",
            )
            session.commit()

    return {"status": "completed", "switches_processed": len(switch_results), "results": switch_results}
