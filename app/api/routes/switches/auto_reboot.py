from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import func, select

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.core.config import settings
from app.domains.inventory.ap_auto_reboot import (
    parse_allowed_stores,
    run_ap_reboot_for_switch,
    switch_eligible_for_auto_reboot,
)
from app.domains.inventory.models import SwitchAccessPoint
from app.domains.inventory.schemas import AutoRebootSummary
from app.domains.operations.models import EventLog

from ._shared import (
    _acquire_switch_write_lock,
    _enforce_switch_cooldown,
    _get_switch_or_404,
    _release_switch_write_lock,
)

router = APIRouter(tags=["switches"])

_AP_REBOOT_OK_EVENTS = {"ap_auto_reboot", "ap_auto_reboot_recovering_hung"}


@router.post("/{switch_id}/auto-reboot/run", dependencies=[Depends(get_current_active_superuser)])
async def run_switch_auto_reboot_now(switch_id: uuid.UUID, session: SessionDep) -> dict:
    switch = _get_switch_or_404(session, switch_id)
    if not settings.AUTO_REBOOT_AP_ENABLED:
        raise HTTPException(status_code=400, detail="Auto-reboot is disabled globally (AUTO_REBOOT_AP_ENABLED)")

    allowed_stores = parse_allowed_stores(settings.AUTO_REBOOT_AP_ALLOWED_STORES)
    eligible, skip_reason = switch_eligible_for_auto_reboot(switch, allowed_stores)
    if not eligible:
        raise HTTPException(status_code=400, detail=f"Switch not eligible for auto-reboot: {skip_reason}")

    lock_key = await _acquire_switch_write_lock(switch_id)
    await _enforce_switch_cooldown(switch_id=switch_id, port="*", operation="auto_reboot_manual_run")
    try:
        return await run_ap_reboot_for_switch(session, switch)
    finally:
        await _release_switch_write_lock(lock_key)


@router.get("/{switch_id}/auto-reboot/history")
async def get_switch_auto_reboot_history(
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
            EventLog.event_type.like("ap_auto_reboot%"),
        )
        .order_by(EventLog.created_at.desc())
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


@router.get("/auto-reboot/summary", response_model=AutoRebootSummary)
async def get_auto_reboot_summary(
    session: SessionDep,
    current_user: CurrentUser,
    hours: int = Query(default=24, ge=1, le=168),
) -> AutoRebootSummary:
    """Fleet-wide view of the scheduled AP reboot cycle, for the Dashboard.

    Per-switch history already exists on each switch card; this rolls it up
    across every store so an operator doesn't have to open 32 cards to see
    whether the last cycle went cleanly.
    """
    since = datetime.now(UTC) - timedelta(hours=hours)
    rows = session.exec(
        select(EventLog).where(
            EventLog.event_type.like("ap_auto_reboot%"),
            EventLog.created_at >= since,
        )
    ).all()

    # Unlike the other stats, this one is current state, not a windowed
    # event count - an AP stays "needing attention" for as long as it's
    # excluded, however many days that spans, not just the last N hours.
    aps_needing_attention = session.exec(
        select(func.count()).select_from(SwitchAccessPoint).where(SwitchAccessPoint.needs_attention_since.is_not(None))
    ).one()

    if not rows:
        return AutoRebootSummary(
            last_cycle_at=None,
            window_hours=hours,
            switches_processed=0,
            aps_rebooted_ok=0,
            aps_failed=0,
            switches_skipped=0,
            aps_needing_attention=aps_needing_attention,
        )

    return AutoRebootSummary(
        last_cycle_at=max(row.created_at for row in rows),
        window_hours=hours,
        switches_processed=len({row.device_name for row in rows if row.device_name}),
        aps_rebooted_ok=sum(1 for row in rows if row.event_type in _AP_REBOOT_OK_EVENTS),
        aps_failed=sum(1 for row in rows if row.event_type == "ap_auto_reboot_failed"),
        switches_skipped=sum(1 for row in rows if row.event_type == "ap_auto_reboot_skipped"),
        aps_needing_attention=aps_needing_attention,
    )
