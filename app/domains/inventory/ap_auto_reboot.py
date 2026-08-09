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

A live CDP scan only sees APs healthy enough to still announce themselves,
so a hung AP - the one most in need of a reboot - would otherwise never be
reached. app.domains.inventory.ap_registry remembers every AP a switch has
ever reported; on each cycle we reboot the ones missing from the live scan
(hung) first, after confirming something is actually drawing PoE on that
port, then the ones that responded normally.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlmodel import Session, select

from app.core.config import settings
from app.domains.inventory.ap_registry import (
    MergedAccessPoint,
    get_known_aps,
    merge_live_and_known,
    record_seen_aps,
    recover_missing_macs_from_registry,
    register_reboot_outcome,
)
from app.domains.inventory.models import NetworkSwitch
from app.observability.metrics import ap_auto_reboot_total
from app.services.cisco_ssh import CiscoSSH, get_access_points, get_port_poe_power, poe_cycle_ap
from app.services.event_log import write_event_log

logger = logging.getLogger(__name__)

REQUIRED_AP_VLAN = 20


def parse_allowed_stores(raw: str) -> set[str]:
    return {_normalize_store_name(s) for s in raw.split(",") if s.strip()}


def _normalize_store_name(name: str) -> str:
    # Store codes are inconsistently typed in Cyrillic vs Latin (e.g. "А12"
    # vs "A1"), so map Cyrillic look-alike letters to their Latin equivalent
    # before comparing against the allowlist.
    cyrillic_to_latin = str.maketrans("АВЕКМНОРСТХаес", "ABEKMHOPCTXaec")
    return name.strip().upper().translate(cyrillic_to_latin)


def switch_eligible_for_auto_reboot(switch: NetworkSwitch, allowed_stores: set[str]) -> tuple[bool, str | None]:
    """Shared gate for both the scheduled cycle and the manual "run now" trigger."""
    if switch.vendor != "cisco":
        return False, f"vendor {switch.vendor} not supported"
    if switch.ap_vlan != REQUIRED_AP_VLAN:
        return False, f"ap_vlan={switch.ap_vlan} (only VLAN {REQUIRED_AP_VLAN} is allowed)"
    if _normalize_store_name(switch.name) not in allowed_stores:
        return False, "store not in AUTO_REBOOT_AP_ALLOWED_STORES allowlist"
    return True, None


async def _verify_ap_back_online(
    switch: NetworkSwitch, mac_address: str, ssh: CiscoSSH | None = None
) -> bool:
    """Poll for the AP to reappear via CDP instead of checking once.

    A single fixed pause was too short for real hardware: APs commonly take
    well over a minute to boot and start advertising CDP again, so a
    one-shot check right after the pause reported "failed" on recovered APs
    every time. This checks repeatedly up to a bounded total wait.

    Pass `ssh` to reuse the cycle's existing connection; without it each poll
    opens its own, which is up to twelve handshakes for a single AP.
    """
    max_wait = settings.AUTO_REBOOT_AP_VERIFY_MAX_WAIT_SECONDS
    interval = max(settings.AUTO_REBOOT_AP_VERIFY_POLL_INTERVAL_SECONDS, 1)
    elapsed = 0
    while elapsed < max_wait:
        await asyncio.sleep(interval)
        elapsed += interval
        aps = await asyncio.to_thread(
            get_access_points,
            switch.ip_address,
            switch.ssh_username,
            switch.ssh_password,
            switch.enable_password,
            switch.ssh_port,
            switch.ap_vlan,
            ssh,
        )
        if aps and any(candidate.mac_address == mac_address for candidate in aps):
            return True
    return False


async def run_ap_reboot_for_switch(session: Session, switch: NetworkSwitch) -> dict:
    """Run one switch's scheduled AP reboot cycle over a single SSH session.

    Every step used to open and tear down its own connection: the CDP scan,
    the PoE check, the power-cycle, and each of up to twelve verification
    polls. One AP could therefore cost more than twenty handshakes to the
    same switch - roughly a minute of pure connection setup - and risked
    running into the switch's VTY session limit exactly when several tasks
    overlapped.
    """
    ssh = CiscoSSH(
        switch.ip_address,
        switch.ssh_username,
        switch.ssh_password,
        switch.enable_password,
        switch.ssh_port,
    )
    try:
        return await _run_ap_reboot_cycle(session, switch, ssh)
    finally:
        await asyncio.to_thread(ssh.close)


async def _run_ap_reboot_cycle(session: Session, switch: NetworkSwitch, ssh: CiscoSSH) -> dict:
    is_dry_run = switch.auto_reboot_mode != "live"
    mode_label = "dry_run" if is_dry_run else "live"

    live_aps = await asyncio.to_thread(
        get_access_points,
        switch.ip_address,
        switch.ssh_username,
        switch.ssh_password,
        switch.enable_password,
        switch.ssh_port,
        switch.ap_vlan,
        ssh,
    )

    if live_aps is None:
        # Couldn't reach the switch this cycle at all - do NOT treat this as
        # "every known AP went silent". Skip the cycle entirely rather than
        # rebooting anything on unreliable information; a real hang is still
        # caught on the next cycle that actually manages to scan.
        write_event_log(
            session,
            severity="warning",
            category="network",
            event_type="ap_auto_reboot_skipped",
            device_kind="switch",
            device_name=switch.name,
            ip_address=switch.ip_address,
            message=f"Auto-reboot ({mode_label}): could not reach {switch.name} via SSH this cycle, skipping",
        )
        session.commit()
        _register_switch_outcome_and_maybe_escalate(session, switch=switch, reachable=False, has_known_aps=None)
        return {"switch": switch.name, "mode": mode_label, "aps_found": 0, "results": [], "skipped": "switch_unreachable"}

    known_rows = get_known_aps(session, switch_id=switch.id)
    live_aps = recover_missing_macs_from_registry(live_aps, known_rows)
    live_aps = [ap for ap in live_aps if ap.port and ap.mac_address]

    record_seen_aps(session, switch_id=switch.id, live_aps=live_aps)
    merged = merge_live_and_known(live_aps, known_rows, vlan=switch.ap_vlan)
    _register_switch_outcome_and_maybe_escalate(session, switch=switch, reachable=True, has_known_aps=bool(merged))

    # Hung (known but not responding) first - that's the AP that actually
    # needs the reboot. Excluded ones are dropped entirely.
    targets = [ap for ap in merged if not ap.exclude_from_auto_reboot]
    targets.sort(key=lambda ap: ap.is_responding)
    targets = targets[: settings.AUTO_REBOOT_AP_MAX_PER_SWITCH]

    if not targets:
        message = (
            f"Auto-reboot ({mode_label}): no VLAN {switch.ap_vlan} access points found on {switch.name}"
            if not merged
            else (
                f"Auto-reboot ({mode_label}): {len(merged)} known VLAN {switch.ap_vlan} access point(s) on "
                f"{switch.name}, all excluded from auto-reboot"
            )
        )
        write_event_log(
            session,
            severity="info",
            category="network",
            event_type="ap_auto_reboot_skipped",
            device_kind="switch",
            device_name=switch.name,
            ip_address=switch.ip_address,
            message=message,
        )
        session.commit()
        return {"switch": switch.name, "mode": mode_label, "aps_found": 0, "results": []}

    results: list[dict] = []
    for ap in targets:
        result = await _handle_one_ap(session, switch, ap, is_dry_run=is_dry_run, mode_label=mode_label, ssh=ssh)
        results.append(result)

        # Space this switch's AP reboots out over time instead of running
        # them back-to-back, so the store never loses every AP in one burst.
        if ap is not targets[-1]:
            await asyncio.sleep(settings.AUTO_REBOOT_AP_PAUSE_SECONDS)

    return {"switch": switch.name, "mode": mode_label, "aps_found": len(targets), "results": results}


async def _handle_one_ap(
    session: Session,
    switch: NetworkSwitch,
    ap: MergedAccessPoint,
    *,
    is_dry_run: bool,
    mode_label: str,
    ssh: CiscoSSH | None = None,
) -> dict:
    hung_prefix = "" if ap.is_responding else "[HUNG] "

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
                f"[DRY RUN] {hung_prefix}Would PoE-cycle AP {ap.mac_address} (port {ap.port}) "
                f"on {switch.name}, VLAN {switch.ap_vlan}"
            ),
        )
        ap_auto_reboot_total.labels(switch=switch.name, result="dry_run").inc()
        return {"port": ap.port, "mac_address": ap.mac_address, "hung": not ap.is_responding, "action": "dry_run"}

    if not ap.is_responding:
        # A hung AP known only from the registry might just be an empty port
        # now (device removed, cabling changed) - confirm something is
        # actually drawing power before cycling it.
        power = await asyncio.to_thread(
            get_port_poe_power,
            switch.ip_address,
            switch.ssh_username,
            switch.ssh_password,
            switch.enable_password,
            switch.ssh_port,
            ap.port,
            ssh,
        )
        if not power:
            write_event_log(
                session,
                severity="info",
                category="network",
                event_type="ap_auto_reboot_skipped",
                device_kind="switch",
                device_name=switch.name,
                ip_address=switch.ip_address,
                message=(
                    f"Known AP {ap.mac_address} (port {ap.port}) on {switch.name} is silent and port has no "
                    "PoE draw - skipping (likely unplugged, not hung)"
                ),
            )
            session.commit()
            ap_auto_reboot_total.labels(switch=switch.name, result="skipped_no_power").inc()
            _register_outcome_and_maybe_escalate(session, switch=switch, ap=ap, recovered=None)
            return {"port": ap.port, "mac_address": ap.mac_address, "hung": True, "action": "skipped_no_power"}

    ok = await asyncio.to_thread(
        poe_cycle_ap,
        switch.ip_address,
        switch.ssh_username,
        switch.ssh_password,
        switch.enable_password,
        switch.ssh_port,
        ap.port,
        ssh,
    )
    write_event_log(
        session,
        severity="info" if ok else "error",
        category="network",
        event_type="ap_auto_reboot_recovering_hung" if not ap.is_responding else "ap_auto_reboot",
        device_kind="switch",
        device_name=switch.name,
        ip_address=switch.ip_address,
        message=(
            f"Auto-reboot: {hung_prefix}PoE-cycled AP {ap.mac_address} (port {ap.port}) on {switch.name}: "
            f"{'ok' if ok else 'command failed'}"
        ),
    )
    session.commit()

    came_back = False
    if ok:
        # Polls repeatedly rather than a single fixed-delay check - see
        # _verify_ap_back_online for why (real APs take well over a minute
        # to reappear in CDP after a PoE cycle).
        came_back = await _verify_ap_back_online(switch, ap.mac_address, ssh)
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
                    f"on VLAN {switch.ap_vlan} within {settings.AUTO_REBOOT_AP_VERIFY_MAX_WAIT_SECONDS}s "
                    "after reboot"
                ),
            )
            session.commit()

    if not ok:
        metric_result = "command_failed"
    elif came_back:
        metric_result = "hung_recovered" if not ap.is_responding else "ok"
    else:
        metric_result = "failed"
    ap_auto_reboot_total.labels(switch=switch.name, result=metric_result).inc()
    _register_outcome_and_maybe_escalate(session, switch=switch, ap=ap, recovered=came_back if ok else False)

    return {
        "port": ap.port,
        "mac_address": ap.mac_address,
        "hung": not ap.is_responding,
        "action": "rebooted",
        "ok": ok,
        "back_online": came_back,
    }


def _register_outcome_and_maybe_escalate(
    session: Session, *, switch: NetworkSwitch, ap: MergedAccessPoint, recovered: bool | None
) -> None:
    _row, escalated = register_reboot_outcome(
        session,
        switch_id=switch.id,
        mac_address=ap.mac_address,
        recovered=recovered,
        threshold=settings.AUTO_REBOOT_AP_ESCALATE_AFTER_CYCLES,
    )
    if not escalated:
        return
    reason = (
        "has shown no PoE draw" if recovered is None else "has failed to come back online after a reboot"
    )
    write_event_log(
        session,
        severity="critical",
        category="network",
        event_type="ap_auto_reboot_needs_attention",
        device_kind="switch",
        device_name=switch.name,
        ip_address=switch.ip_address,
        message=(
            f"AP {ap.mac_address} (port {ap.port}) on {switch.name} {reason} for "
            f"{settings.AUTO_REBOOT_AP_ESCALATE_AFTER_CYCLES} consecutive cycles - excluded from "
            "auto-reboot until checked on site and manually re-included"
        ),
    )
    session.commit()
    ap_auto_reboot_total.labels(switch=switch.name, result="needs_attention").inc()


def _register_switch_outcome_and_maybe_escalate(
    session: Session, *, switch: NetworkSwitch, reachable: bool, has_known_aps: bool | None
) -> None:
    """Track a scheduled cycle's switch-level outcome (as opposed to any one
    AP's) and escalate a persistent streak.

    Unlike an AP that keeps failing to recover, the switch is never
    auto-excluded here - retrying SSH next cycle is a cheap few-second probe,
    not a power-cycle of live hardware, so there's no safety reason to stop
    trying. This only decides when a human should be told it's not just a
    one-off blip (bad credentials, VLAN misconfiguration, etc.).
    """
    threshold = settings.AUTO_REBOOT_AP_ESCALATE_AFTER_CYCLES
    reason: str | None = None

    if not reachable:
        switch.consecutive_unreachable_cycles += 1
        if switch.consecutive_unreachable_cycles >= threshold and switch.switch_needs_attention_since is None:
            reason = (
                f"could not be reached via SSH for {switch.consecutive_unreachable_cycles} consecutive cycles "
                "- check credentials/connectivity"
            )
    else:
        switch.consecutive_unreachable_cycles = 0
        if has_known_aps:
            switch.consecutive_no_aps_found_cycles = 0
            switch.switch_needs_attention_since = None
        else:
            switch.consecutive_no_aps_found_cycles += 1
            if switch.consecutive_no_aps_found_cycles >= threshold and switch.switch_needs_attention_since is None:
                reason = (
                    f"found zero access points on VLAN {switch.ap_vlan} for "
                    f"{switch.consecutive_no_aps_found_cycles} consecutive cycles - check ap_vlan or whether "
                    "this switch actually has any APs"
                )

    if reason is not None:
        switch.switch_needs_attention_since = datetime.now(UTC)

    switch.updated_at = datetime.now(UTC)
    session.add(switch)
    session.commit()

    if reason is None:
        return
    write_event_log(
        session,
        severity="critical",
        category="network",
        event_type="ap_auto_reboot_switch_needs_attention",
        device_kind="switch",
        device_name=switch.name,
        ip_address=switch.ip_address,
        message=f"Auto-reboot: switch {switch.name} {reason}",
    )
    session.commit()
    ap_auto_reboot_total.labels(switch=switch.name, result="switch_needs_attention").inc()


def get_eligible_switches_for_auto_reboot(session: Session) -> list[NetworkSwitch]:
    """Switches currently eligible for the scheduled AP reboot cycle.

    Sorted by name so dispatch order - and therefore which switch lands at
    which staggered offset - is stable across cycles rather than depending
    on incidental DB row order.
    """
    if not settings.AUTO_REBOOT_AP_ENABLED:
        return []

    allowed_stores = parse_allowed_stores(settings.AUTO_REBOOT_AP_ALLOWED_STORES)
    if not allowed_stores:
        return []

    switches = session.exec(select(NetworkSwitch).where(NetworkSwitch.auto_reboot_aps_enabled)).all()
    eligible: list[NetworkSwitch] = []
    for switch in switches:
        ok, skip_reason = switch_eligible_for_auto_reboot(switch, allowed_stores)
        if ok:
            eligible.append(switch)
        else:
            logger.info("Auto-reboot skipped for %s: %s", switch.name, skip_reason)

    eligible.sort(key=lambda sw: sw.name)
    return eligible
