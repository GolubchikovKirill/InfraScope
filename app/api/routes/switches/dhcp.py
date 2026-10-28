from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.core.config import settings
from app.domains.inventory.ap_auto_reboot import parse_allowed_stores
from app.domains.inventory.dhcp_clear import (
    parse_clear_actions,
    run_dhcp_clear_for_switch,
    switch_eligible_for_dhcp_clear,
)
from app.domains.inventory.schemas import DhcpBindingInfo, DhcpClearResponse, DhcpDiagnosticsInfo, DhcpPoolInfo
from app.domains.operations.models import EventLog
from app.services.cisco_dhcp import VALID_ACTIONS, DhcpDiagnostics, plan_clear, run_dhcp_diagnostics

from ._shared import (
    _acquire_switch_write_lock,
    _enforce_switch_cooldown,
    _get_switch_or_404,
    _release_switch_write_lock,
)

router = APIRouter(tags=["switches"])


def _to_public(diag: DhcpDiagnostics) -> DhcpDiagnosticsInfo:
    plan = plan_clear(
        diag,
        actions=parse_clear_actions(settings.DHCP_CLEAR_ACTIONS) & VALID_ACTIONS,
        max_bindings=settings.DHCP_CLEAR_MAX_BINDINGS,
    )
    return DhcpDiagnosticsInfo(
        vlan=diag.vlan,
        role=diag.role,
        pools=[
            DhcpPoolInfo(
                name=p.name,
                total_addresses=p.total_addresses,
                leased_addresses=p.leased_addresses,
                ranges=p.ranges,
            )
            for p in diag.pools
        ],
        bindings_total=len(diag.bindings),
        ap_bindings=[DhcpBindingInfo(**vars(b)) for b in diag.ap_bindings],
        conflicts=diag.conflicts,
        helper_addresses=diag.helper_addresses,
        svi_ip=diag.svi_ip,
        snooping_enabled=diag.snooping_enabled,
        snooping_vlans=diag.snooping_vlans,
        arp_inspection_vlans=diag.arp_inspection_vlans,
        ip_source_guard=diag.ip_source_guard,
        unsupported=diag.unsupported,
        planned_commands=plan.commands,
        skipped_reasons=plan.skipped,
    )


@router.get("/{switch_id}/dhcp", response_model=DhcpDiagnosticsInfo)
async def get_switch_dhcp_diagnostics(
    switch_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> DhcpDiagnosticsInfo:
    """Read-only: who serves DHCP for the AP VLAN, what it has leased, and what
    a cleanup would do. Sends only `show` commands."""
    switch = _get_switch_or_404(session, switch_id)
    if switch.vendor != "cisco":
        raise HTTPException(status_code=400, detail="DHCP diagnostics are available for Cisco switches")

    diag = await asyncio.to_thread(
        run_dhcp_diagnostics,
        switch.ip_address,
        switch.ssh_username,
        switch.ssh_password,
        switch.enable_password,
        switch.ssh_port,
        switch.ap_vlan,
    )
    if diag is None:
        raise HTTPException(status_code=502, detail="Could not read DHCP state from the switch via SSH")
    return _to_public(diag)


@router.post(
    "/{switch_id}/dhcp/clear",
    response_model=DhcpClearResponse,
    dependencies=[Depends(get_current_active_superuser)],
)
async def run_switch_dhcp_clear_now(switch_id: uuid.UUID, session: SessionDep) -> dict:
    """Run one cleanup now, under the switch's own mode: `dry_run` only reports
    what would be sent, `live` sends it. Same gates as the scheduled cycle."""
    switch = _get_switch_or_404(session, switch_id)
    if not settings.DHCP_CLEAR_ENABLED:
        raise HTTPException(status_code=400, detail="DHCP cleanup is disabled globally (DHCP_CLEAR_ENABLED)")
    if not switch.dhcp_clear_enabled:
        raise HTTPException(status_code=409, detail="DHCP cleanup is disabled for this switch")

    allowed_stores = parse_allowed_stores(settings.DHCP_CLEAR_ALLOWED_STORES)
    eligible, skip_reason = switch_eligible_for_dhcp_clear(switch, allowed_stores)
    if not eligible:
        raise HTTPException(status_code=400, detail=f"Switch not eligible for DHCP cleanup: {skip_reason}")

    lock_key = await _acquire_switch_write_lock(switch_id)
    try:
        await _enforce_switch_cooldown(switch_id=switch_id, port="*", operation="dhcp_clear_manual_run")
        return await run_dhcp_clear_for_switch(session, switch)
    finally:
        await _release_switch_write_lock(lock_key)


@router.get("/{switch_id}/dhcp/history")
def get_switch_dhcp_history(
    switch_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict]:
    switch = _get_switch_or_404(session, switch_id)
    rows = session.exec(
        select(EventLog)
        .where(
            EventLog.device_name == switch.name,
            col(EventLog.event_type).like("dhcp_clear%"),
        )
        .order_by(col(EventLog.created_at).desc())
        .limit(limit)
    ).all()
    return [
        {
            "created_at": row.created_at,
            "severity": row.severity,
            "event_type": row.event_type,
            "message": row.message,
        }
        for row in rows
    ]
