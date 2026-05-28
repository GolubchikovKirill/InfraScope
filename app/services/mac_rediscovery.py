from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from app.services.device_poll import find_devices_by_macs

_MAC_HEX_RE = re.compile(r"^[0-9a-f]{12}$")


@dataclass(frozen=True)
class MacRediscoveryTarget:
    device_kind: str
    entity_id: str
    name: str
    current_ip: str | None
    mac_address: str


@dataclass(frozen=True)
class MacRediscoveryMatch:
    target: MacRediscoveryTarget
    normalized_mac: str
    new_ip: str

    @property
    def moved(self) -> bool:
        return bool(self.target.current_ip and self.new_ip != self.target.current_ip)


def normalize_mac(value: str | None) -> str | None:
    if not value:
        return None
    compact = re.sub(r"[^0-9a-fA-F]", "", value)
    if not _MAC_HEX_RE.match(compact.lower()):
        return None
    pairs = [compact[i : i + 2].lower() for i in range(0, 12, 2)]
    return ":".join(pairs)


async def resolve_devices_by_mac(
    targets: list[MacRediscoveryTarget],
    *,
    subnets: list[str] | None = None,
) -> list[MacRediscoveryMatch]:
    mac_to_targets: dict[str, list[MacRediscoveryTarget]] = defaultdict(list)
    for target in targets:
        normalized = normalize_mac(target.mac_address)
        if normalized:
            mac_to_targets[normalized].append(target)

    if not mac_to_targets:
        return []

    found = await find_devices_by_macs(list(mac_to_targets), subnets=subnets)
    normalized_found = {
        normalized: ip
        for mac, ip in found.items()
        if (normalized := normalize_mac(mac)) and ip
    }

    matches: list[MacRediscoveryMatch] = []
    for mac, target_group in mac_to_targets.items():
        new_ip = normalized_found.get(mac)
        if not new_ip:
            continue
        matches.extend(
            MacRediscoveryMatch(target=target, normalized_mac=mac, new_ip=new_ip)
            for target in target_group
        )
    return matches
