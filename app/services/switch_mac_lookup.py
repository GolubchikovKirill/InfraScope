"""Global MAC->IP map built from switches' own ARP tables.

Used as a fast, quiet first source for MAC-based device rediscovery, ahead
of the ARP-table + ping-sweep fallback in mac_rediscovery.py. Reading a
table a switch already maintains costs nothing on the network; a ping sweep
across a whole subnet does. Cached in Redis since it costs one SSH round
trip per switch - not something to redo on every single rediscovery call.
"""

from __future__ import annotations

import asyncio
import json
import logging

from sqlmodel import Session, select

from app.core.redis import get_redis
from app.domains.inventory.models import NetworkSwitch
from app.services.cisco_ssh import get_switch_arp_mac_map
from app.services.mac_rediscovery import normalize_mac

logger = logging.getLogger(__name__)

CACHE_KEY = "mac_map:switches"
CACHE_TTL_SECONDS = 600
SSH_CONCURRENCY = 4


async def build_switch_mac_map(session: Session) -> dict[str, str]:
    redis = None
    try:
        redis = await get_redis()
        cached = await redis.get(CACHE_KEY)
        if cached:
            return json.loads(cached)
    except Exception as exc:
        logger.debug("Switch MAC map cache read failed: %s", exc)

    switches = session.exec(
        select(NetworkSwitch).where(NetworkSwitch.vendor == "cisco", NetworkSwitch.is_online == True)  # noqa: E712
    ).all()
    if not switches:
        return {}

    semaphore = asyncio.Semaphore(SSH_CONCURRENCY)

    async def _fetch(switch: NetworkSwitch) -> dict[str, str]:
        async with semaphore:
            try:
                return await asyncio.to_thread(
                    get_switch_arp_mac_map,
                    switch.ip_address,
                    switch.ssh_username,
                    switch.ssh_password,
                    switch.enable_password,
                    switch.ssh_port,
                )
            except Exception as exc:
                logger.debug("Switch MAC map fetch failed for %s: %s", switch.name, exc)
                return {}

    results = await asyncio.gather(*[_fetch(sw) for sw in switches])
    merged: dict[str, str] = {}
    for result in results:
        merged.update(result)

    if redis is not None:
        try:
            await redis.setex(CACHE_KEY, CACHE_TTL_SECONDS, json.dumps(merged))
        except Exception as exc:
            logger.debug("Switch MAC map cache write failed: %s", exc)

    return merged


async def find_ip_by_mac_via_switches(session: Session, mac_address: str) -> str | None:
    normalized = normalize_mac(mac_address)
    if not normalized:
        return None
    mac_map = await build_switch_mac_map(session)
    return mac_map.get(normalized)
