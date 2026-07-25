from __future__ import annotations

import hashlib
import json
import logging

from sqlmodel import Session, select

from app.domains.inventory.models import NetworkSwitch, SwitchPortSnapshot
from app.services.switches import resolve_switch_provider
from app.services.switches.base import SwitchPortState

logger = logging.getLogger(__name__)


def get_switches_for_snapshot(session: Session) -> list[NetworkSwitch]:
    return list(session.exec(select(NetworkSwitch).order_by(NetworkSwitch.name)).all())


def _serialize_ports(ports: list[SwitchPortState]) -> list[dict]:
    # Only configuration fields, not live/transient state (link status, PoE
    # wattage, MAC count) - those change constantly and would make every
    # check look like a config change.
    return [
        {
            "port": p.port,
            "description": p.description,
            "admin_status": p.admin_status,
            "port_mode": p.port_mode,
            "access_vlan": p.access_vlan,
            "trunk_native_vlan": p.trunk_native_vlan,
            "trunk_allowed_vlans": p.trunk_allowed_vlans,
            "poe_enabled": p.poe_enabled,
        }
        for p in sorted(ports, key=lambda port: port.port)
    ]


def _hash_ports(serialized: list[dict]) -> str:
    payload = json.dumps(serialized, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def capture_switch_port_snapshot(session: Session, switch: NetworkSwitch) -> SwitchPortSnapshot | None:
    """Fetch current port config and store a new snapshot row only if it
    changed since the last stored snapshot for this switch.

    Returns the new row if one was written, or None if the switch was
    unreachable or nothing changed since the last snapshot.
    """
    provider = resolve_switch_provider(switch)
    try:
        ports = provider.get_ports(switch)
    except Exception as exc:
        logger.warning("Port snapshot failed for %s: %s", switch.name, exc)
        return None

    serialized = _serialize_ports(ports)
    new_hash = _hash_ports(serialized)

    last = session.exec(
        select(SwitchPortSnapshot)
        .where(SwitchPortSnapshot.switch_id == switch.id)
        .order_by(SwitchPortSnapshot.captured_at.desc())
        .limit(1)
    ).first()
    if last is not None and last.ports_hash == new_hash:
        return None

    snapshot = SwitchPortSnapshot(switch_id=switch.id, ports_hash=new_hash, ports_json=serialized)
    session.add(snapshot)
    session.commit()
    session.refresh(snapshot)
    return snapshot
