"""Persistent registry of Wi-Fi APs ever seen on a switch's ap_vlan via CDP.

A live CDP scan only sees APs currently healthy enough to announce
themselves, so a hung AP - the one most in need of a reboot - is invisible
to it. This module remembers every AP a switch has ever reported and lets
callers (the auto-reboot cycle, the UI) tell "responding now" apart from
"known but currently silent" (a strong hang signal) apart from "excluded on
purpose" (e.g. a guest device that isn't actually one of our APs).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlmodel import Session, select

from app.domains.inventory.models import SwitchAccessPoint
from app.services.cisco_ssh import APInfo

# APs not seen in this long are considered stale and excluded from the
# "known but hung" set - most likely decommissioned or genuinely gone,
# not just having a bad day.
KNOWN_AP_STALE_AFTER_DAYS = 7


@dataclass
class MergedAccessPoint:
    mac_address: str
    port: str
    vlan: int
    cdp_name: str | None
    ip_address: str | None
    cdp_platform: str | None
    poe_power: str | None
    poe_status: str | None
    is_responding: bool
    last_seen_at: datetime | None
    exclude_from_auto_reboot: bool


def record_seen_aps(session: Session, *, switch_id: uuid.UUID, live_aps: list[APInfo]) -> None:
    """Upsert a registry row for every AP seen in a live scan."""
    if not live_aps:
        return
    now = datetime.now(UTC)
    existing = {
        row.mac_address: row
        for row in session.exec(
            select(SwitchAccessPoint).where(SwitchAccessPoint.switch_id == switch_id)
        ).all()
    }
    for ap in live_aps:
        if not ap.mac_address or not ap.port:
            continue
        row = existing.get(ap.mac_address)
        if row is None:
            row = SwitchAccessPoint(switch_id=switch_id, mac_address=ap.mac_address, port=ap.port)
        row.port = ap.port
        if ap.cdp_name:
            row.cdp_name = ap.cdp_name
        row.last_seen_at = now
        row.is_active = True
        row.updated_at = now
        session.add(row)
    session.commit()


def recover_missing_macs_from_registry(
    live_aps: list[APInfo], known_rows: list[SwitchAccessPoint]
) -> list[APInfo]:
    """Fall back to a known MAC when CDP found an AP but its MAC couldn't be
    resolved this scan.

    Default-named APs ("APxxxx.xxxx.xxxx") already get their MAC decoded
    straight from the CDP name in cisco_ssh.py. Custom-named APs (e.g.
    "AP_A6_VS") have no such shortcut and depend entirely on the switch's
    MAC address table, whose entry for a given port can be momentarily
    stale even when CDP's own (much longer-lived) entry is solid - exactly
    what caused A30's AP_A6_VS to intermittently show as unresponsive.

    Only applied when both port AND cdp_name match a known registry row:
    that combination is specific enough that reusing the MAC is safe,
    whereas matching on port alone could misattribute a different physical
    device that happens to occupy the same port later.
    """
    by_port_name = {(row.port, row.cdp_name): row.mac_address for row in known_rows if row.cdp_name}
    for ap in live_aps:
        if ap.mac_address or not ap.port or not ap.cdp_name:
            continue
        recovered = by_port_name.get((ap.port, ap.cdp_name))
        if recovered:
            ap.mac_address = recovered
    return live_aps


def get_known_aps(session: Session, *, switch_id: uuid.UUID) -> list[SwitchAccessPoint]:
    return session.exec(
        select(SwitchAccessPoint).where(
            SwitchAccessPoint.switch_id == switch_id,
            SwitchAccessPoint.is_active,
        )
    ).all()


def merge_live_and_known(
    live_aps: list[APInfo], known_rows: list[SwitchAccessPoint], *, vlan: int
) -> list[MergedAccessPoint]:
    """Combine a live CDP scan with the registry: live APs plus any known AP
    that didn't show up this time (a hang signal), oldest-stale ones dropped.
    """
    live_by_mac = {ap.mac_address: ap for ap in live_aps if ap.mac_address}
    merged: list[MergedAccessPoint] = []

    for ap in live_aps:
        known = next((row for row in known_rows if row.mac_address == ap.mac_address), None)
        merged.append(
            MergedAccessPoint(
                mac_address=ap.mac_address,
                port=ap.port,
                vlan=vlan,
                cdp_name=ap.cdp_name,
                ip_address=ap.ip_address,
                cdp_platform=ap.cdp_platform,
                poe_power=ap.poe_power,
                poe_status=ap.poe_status,
                is_responding=True,
                last_seen_at=known.last_seen_at if known else datetime.now(UTC),
                exclude_from_auto_reboot=known.exclude_from_auto_reboot if known else False,
            )
        )

    stale_cutoff = datetime.now(UTC).timestamp() - KNOWN_AP_STALE_AFTER_DAYS * 86400
    for row in known_rows:
        if row.mac_address in live_by_mac:
            continue
        last_seen = row.last_seen_at if row.last_seen_at.tzinfo else row.last_seen_at.replace(tzinfo=UTC)
        if last_seen.timestamp() < stale_cutoff:
            continue
        merged.append(
            MergedAccessPoint(
                mac_address=row.mac_address,
                port=row.port,
                vlan=vlan,
                cdp_name=row.cdp_name,
                ip_address=None,
                cdp_platform=None,
                poe_power=None,
                poe_status=None,
                is_responding=False,
                last_seen_at=row.last_seen_at,
                exclude_from_auto_reboot=row.exclude_from_auto_reboot,
            )
        )

    return merged


def known_aps_as_still_responding(known_rows: list[SwitchAccessPoint], *, vlan: int) -> list[MergedAccessPoint]:
    """Build a merged view for a cycle where the switch could not be scanned
    at all (SSH failed), as opposed to a successful scan that found nothing.

    A failed scan carries no information about which APs are actually up, so
    every known AP is presented as still responding rather than hung - a
    missed scan must never itself look like evidence that APs went silent.
    Real hangs are still caught on the next scan that succeeds.
    """
    return [
        MergedAccessPoint(
            mac_address=row.mac_address,
            port=row.port,
            vlan=vlan,
            cdp_name=row.cdp_name,
            ip_address=None,
            cdp_platform=None,
            poe_power=None,
            poe_status=None,
            is_responding=True,
            last_seen_at=row.last_seen_at,
            exclude_from_auto_reboot=row.exclude_from_auto_reboot,
        )
        for row in known_rows
    ]


def set_ap_excluded(session: Session, *, switch_id: uuid.UUID, mac_address: str, excluded: bool) -> bool:
    """Returns False if the AP isn't in the registry for this switch yet."""
    row = session.exec(
        select(SwitchAccessPoint).where(
            SwitchAccessPoint.switch_id == switch_id,
            SwitchAccessPoint.mac_address == mac_address,
        )
    ).first()
    if row is None:
        return False
    row.exclude_from_auto_reboot = excluded
    row.updated_at = datetime.now(UTC)
    session.add(row)
    session.commit()
    return True
