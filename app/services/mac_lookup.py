from __future__ import annotations

import asyncio
import logging

from app.services.device_poll import poll_device
from app.services.mac_rediscovery import normalize_mac
from app.services.snmp import get_snmp_mac

logger = logging.getLogger(__name__)


async def resolve_mac_for_ip_address(
    ip_address: str | None,
    *,
    snmp_community: str = "public",
    prefer_snmp: bool = True,
) -> str | None:
    if not ip_address:
        return None

    if prefer_snmp:
        try:
            mac = await asyncio.to_thread(get_snmp_mac, ip_address, snmp_community)
            if normalized := normalize_mac(mac):
                return normalized
        except Exception as exc:
            logger.debug("SNMP MAC lookup failed for %s: %s", ip_address, exc)

    try:
        status = await poll_device(ip_address, snmp_community)
    except Exception as exc:
        logger.debug("Generic MAC lookup failed for %s: %s", ip_address, exc)
        return None
    return normalize_mac(status.mac_address)
