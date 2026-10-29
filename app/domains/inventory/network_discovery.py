"""Adding machines the network already knows about to the computer inventory.

The source is the AD DNS zone (see app.services.dns_zone); only names whose
role token is in DNS_DISCOVERY_ROLES are taken, so this adds the store
screens (VNA-TV-*) without flooding the inventory with every till and
server in the domain. Rows are only ever added, never changed or removed,
so a machine deleted from the inventory by hand comes back for as long as
DNS still lists it - remove the DNS record (or the role) to drop it for good.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlmodel import Session, col, select

from app.core.config import settings
from app.domains.inventory.computer_polling import invalidate_computer_cache, probe_computers_bulk
from app.domains.inventory.models import Computer
from app.services.dns_zone import zone_a_records
from app.services.event_log import write_event_log

logger = logging.getLogger(__name__)


@dataclass
class DiscoveryResult:
    zone: str
    seen: int = 0
    matched: int = 0
    added: list[str] = field(default_factory=list)


def discovery_zone() -> str:
    explicit = settings.DNS_DISCOVERY_ZONE.strip().strip(".")
    if explicit:
        return explicit
    suffixes = [s.strip().strip(".") for s in settings.DNS_SEARCH_SUFFIXES.split(",") if s.strip()]
    return suffixes[0] if suffixes else ""


def discovery_roles() -> set[str]:
    return {role.strip().upper() for role in settings.DNS_DISCOVERY_ROLES.split(",") if role.strip()}


def role_of(hostname: str) -> str | None:
    """The role token of a `<SITE>-<ROLE>-<NUM>` name: VNA-TV-1301 -> "TV".
    Same rule as the remote-access type tag."""
    parts = hostname.split("-")
    if len(parts) < 3:
        return None
    return parts[1].strip().upper() or None


def discover_computers_from_dns(session: Session, records: dict[str, str] | None = None) -> DiscoveryResult:
    """Add every DNS-registered machine of a discovered role that the inventory lacks.

    `records` (name -> IP) is for tests; normally the zone is transferred here.
    Names are stored upper-case, as the existing inventory spells them.
    """
    zone = discovery_zone()
    result = DiscoveryResult(zone=zone)
    roles = discovery_roles()
    if not roles:
        return result
    if records is None:
        records = zone_a_records(settings.DNS_SERVER, zone)
    result.seen = len(records)

    known = {hostname.lower() for hostname in session.exec(select(Computer.hostname)).all() if hostname}
    for name in sorted(records, key=str.lower):
        if role_of(name) not in roles:
            continue
        result.matched += 1
        if name.lower() in known:
            continue
        hostname = name.upper()
        session.add(Computer(hostname=hostname, comment=f"Найден в DNS ({zone}), {records[name]}"))
        known.add(name.lower())
        result.added.append(hostname)
        write_event_log(
            session,
            category="inventory",
            event_type="computer_discovered",
            device_kind="computer",
            device_name=hostname,
            ip_address=records[name],
            message=f"Computer '{hostname}' found in DNS zone {zone} and added to the inventory",
        )

    if result.added:
        session.commit()
        logger.info("DNS discovery added %d computers: %s", len(result.added), ", ".join(result.added))
    return result


async def discover_and_probe(session: Session) -> DiscoveryResult:
    """Discovery, then a first reachability probe of what it added, so a new
    screen shows as up or down right away instead of after the next 15-minute
    computer poll."""
    result = await asyncio.to_thread(discover_computers_from_dns, session)
    if not result.added:
        return result
    rows = list(session.exec(select(Computer).where(col(Computer.hostname).in_(result.added))).all())
    probes = await probe_computers_bulk(rows)
    now = datetime.now(UTC)
    for row in rows:
        probe = probes.get(row.id)
        if probe is None:
            continue
        row.is_online = probe.is_online
        row.reachability_reason = probe.reason
        row.last_polled_at = now
        session.add(row)
    session.commit()
    await invalidate_computer_cache()
    return result
