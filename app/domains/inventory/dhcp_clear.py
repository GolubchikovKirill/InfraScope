"""Scheduled DHCP cleanup on switches that serve DHCP for the AP VLAN.

Wi-Fi APs that keep a stale lease or sit on a conflicted address come up with
the wrong IP (or none) after a reboot. On a switch that is itself the DHCP
server, clearing its conflict list and the AP-VLAN leases lets them re-lease
cleanly. This runs shortly before the scheduled AP reboot so the rebooted APs
come back to a clean table.

Same safety shape as app.domains.inventory.ap_auto_reboot: a switch's own
`dhcp_clear_enabled` toggle is necessary but not sufficient - the store must
also be in `settings.DHCP_CLEAR_ALLOWED_STORES` - and `dhcp_clear_mode`
defaults to "dry_run", which reads the switch and logs exactly which commands
it would send without sending any.

What actually gets cleared is decided by app.services.cisco_dhcp.plan_clear,
which refuses unless the switch is provably the DHCP server for the VLAN.
"""

from __future__ import annotations

import asyncio
import logging

from sqlmodel import Session, select

from app.core.config import settings
from app.domains.inventory.ap_auto_reboot import REQUIRED_AP_VLAN, _normalize_store_name, parse_allowed_stores
from app.domains.inventory.models import NetworkSwitch
from app.observability.metrics import dhcp_clear_total
from app.services.cisco_dhcp import VALID_ACTIONS, DhcpClearResult, run_dhcp_clear
from app.services.event_log import write_event_log

logger = logging.getLogger(__name__)


def parse_clear_actions(raw: str) -> set[str]:
    return {a.strip().lower() for a in raw.split(",") if a.strip()}


def switch_eligible_for_dhcp_clear(switch: NetworkSwitch, allowed_stores: set[str]) -> tuple[bool, str | None]:
    """Shared gate for both the scheduled cycle and the manual "run now" trigger."""
    if switch.vendor != "cisco":
        return False, f"vendor {switch.vendor} not supported"
    if switch.ap_vlan != REQUIRED_AP_VLAN:
        return False, f"ap_vlan={switch.ap_vlan} (only VLAN {REQUIRED_AP_VLAN} is allowed)"
    if _normalize_store_name(switch.name) not in allowed_stores:
        return False, "store not in DHCP_CLEAR_ALLOWED_STORES allowlist"
    return True, None


def get_eligible_switches_for_dhcp_clear(session: Session) -> list[NetworkSwitch]:
    """Name-sorted so dispatch order (and each switch's stagger offset) is stable."""
    if not settings.DHCP_CLEAR_ENABLED:
        return []
    allowed_stores = parse_allowed_stores(settings.DHCP_CLEAR_ALLOWED_STORES)
    if not allowed_stores:
        return []

    switches = session.exec(select(NetworkSwitch).where(NetworkSwitch.dhcp_clear_enabled)).all()
    eligible: list[NetworkSwitch] = []
    for switch in switches:
        ok, skip_reason = switch_eligible_for_dhcp_clear(switch, allowed_stores)
        if ok:
            eligible.append(switch)
        else:
            logger.info("DHCP clear skipped for %s: %s", switch.name, skip_reason)
    eligible.sort(key=lambda sw: sw.name)
    return eligible


async def run_dhcp_clear_for_switch(session: Session, switch: NetworkSwitch) -> dict:
    """Run one switch's DHCP cleanup over a single SSH session."""
    is_dry_run = switch.dhcp_clear_mode != "live"
    mode_label = "dry_run" if is_dry_run else "live"
    actions = parse_clear_actions(settings.DHCP_CLEAR_ACTIONS) & VALID_ACTIONS

    result: DhcpClearResult | None = await asyncio.to_thread(
        run_dhcp_clear,
        switch.ip_address,
        switch.ssh_username,
        switch.ssh_password,
        switch.enable_password,
        switch.ssh_port,
        switch.ap_vlan,
        actions=actions,
        max_bindings=settings.DHCP_CLEAR_MAX_BINDINGS,
        dry_run=is_dry_run,
    )

    def _log(severity: str, event_type: str, message: str) -> None:
        write_event_log(
            session,
            severity=severity,
            category="network",
            event_type=event_type,
            device_kind="switch",
            device_name=switch.name,
            ip_address=switch.ip_address,
            message=message,
        )
        session.commit()

    if result is None:
        # Couldn't scan at all: say so, and do not pretend the table is clean.
        _log(
            "warning",
            "dhcp_clear_skipped",
            f"DHCP clear ({mode_label}): could not reach {switch.name} via SSH this cycle, skipping",
        )
        dhcp_clear_total.labels(switch=switch.name, result="unreachable").inc()
        return {"switch": switch.name, "mode": mode_label, "skipped": "switch_unreachable"}

    plan = result.plan
    summary = {
        "switch": switch.name,
        "mode": mode_label,
        "role": result.role,
        "commands_planned": len(plan.commands),
        "bindings_before": result.bindings_before,
        "conflicts_before": result.conflicts_before,
        "skipped": plan.skipped,
    }

    if not plan.commands:
        _log(
            "info",
            "dhcp_clear_skipped",
            f"DHCP clear ({mode_label}): nothing to do on {switch.name} (role={result.role}): "
            + "; ".join(plan.skipped or ["no actions"]),
        )
        dhcp_clear_total.labels(switch=switch.name, result="nothing_to_do").inc()
        return summary

    if result.dry_run:
        _log(
            "info",
            "dhcp_clear_dry_run",
            f"[DRY RUN] Would clear {plan.bindings_to_clear} binding(s) and {plan.conflicts_to_clear} "
            f"conflict(s) on {switch.name}, VLAN {switch.ap_vlan}",
        )
        dhcp_clear_total.labels(switch=switch.name, result="dry_run").inc()
        return summary

    summary.update(
        bindings_cleared=result.bindings_cleared,
        conflicts_cleared=result.conflicts_cleared,
        bindings_after=result.bindings_after,
        conflicts_after=result.conflicts_after,
        errors=result.errors,
    )
    if result.errors:
        _log(
            "error",
            "dhcp_clear_failed",
            f"DHCP clear on {switch.name}: {len(result.errors)} command(s) failed "
            f"({result.bindings_cleared} binding(s), {result.conflicts_cleared} conflict(s) cleared): "
            + "; ".join(result.errors[:3]),
        )
        dhcp_clear_total.labels(switch=switch.name, result="failed").inc()
        return summary

    _log(
        "info",
        "dhcp_clear",
        f"DHCP clear: cleared {result.bindings_cleared} binding(s) and {result.conflicts_cleared} conflict(s) "
        f"on {switch.name}, VLAN {switch.ap_vlan} (bindings {result.bindings_before} -> {result.bindings_after})",
    )
    dhcp_clear_total.labels(switch=switch.name, result="ok").inc()
    return summary
