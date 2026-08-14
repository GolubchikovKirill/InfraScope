from __future__ import annotations

import asyncio
import logging
import subprocess

from app.observability.metrics import snmp_operations_total

from ._pysnmp_compat import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    walk_cmd,
)
from .oids import SNMP_RETRIES, SNMP_TIMEOUT

logger = logging.getLogger(__name__)

OID_IF_PHYS_ADDR = "1.3.6.1.2.1.2.2.1.6"


async def _get_snmp_mac_async(ip_address: str, community: str = "public") -> str | None:
    """Query ifPhysAddress via SNMP to get MAC address."""
    engine = SnmpEngine()
    try:
        try:
            target = await UdpTransportTarget.create((ip_address, 161), timeout=SNMP_TIMEOUT, retries=SNMP_RETRIES)
        except Exception:
            return None

        comm = CommunityData(community)
        try:
            async for err, _, _, vb in walk_cmd(
                engine,
                comm,
                target,
                ContextData(),
                ObjectType(ObjectIdentity(OID_IF_PHYS_ADDR)),
                lexicographicMode=False,
            ):
                if err:
                    break
                for _, val in vb:
                    if hasattr(val, "asOctets"):
                        octets = val.asOctets()
                        if len(octets) == 6 and any(b != 0 for b in octets):
                            return ":".join(f"{b:02x}" for b in octets)
        except Exception:
            pass
        return None
    finally:
        # SnmpEngine opens a UDP socket lazily on first request and never
        # closes it on its own - across enough polling cycles that leaked
        # one file descriptor per call until the container hit its FD limit
        # (Errno 24) and every poll endpoint started returning 500. Must run
        # in the same event loop that issued the request; closing after
        # asyncio.run() returns is a no-op against a loop that's already gone.
        engine.closeDispatcher()


def _get_mac_from_arp(ip_address: str) -> str | None:
    """Read MAC from system ARP table. Works with network_mode: host on Linux."""
    # Ping to populate ARP cache
    try:
        subprocess.run(
            ["ping", "-c", "1", "-W", "1", ip_address],
            capture_output=True,
            timeout=3,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    try:
        with open("/proc/net/arp") as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                if len(parts) >= 4 and parts[0] == ip_address:
                    mac = parts[3].lower()
                    if mac != "00:00:00:00:00:00" and len(mac) == 17:
                        return mac
    except (FileNotFoundError, PermissionError):
        pass

    try:
        out = subprocess.run(
            ["ip", "neigh", "show", ip_address],
            capture_output=True,
            text=True,
            timeout=3,
        ).stdout.strip()
        if "lladdr" in out:
            parts = out.split()
            idx = parts.index("lladdr")
            if idx + 1 < len(parts):
                mac = parts[idx + 1].lower()
                if len(mac) == 17:
                    return mac
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def get_snmp_mac(ip_address: str, community: str = "public") -> str | None:
    """Get MAC via SNMP, with ARP table fallback."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    mac = None
    try:
        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                mac = pool.submit(asyncio.run, _get_snmp_mac_async(ip_address, community)).result()
        else:
            mac = asyncio.run(_get_snmp_mac_async(ip_address, community))
    except Exception:
        snmp_operations_total.labels(operation="get_mac", result="error", reason="exception").inc()
        return None

    # ARP fallback: works with network_mode: host on Linux
    if mac is None:
        mac = _get_mac_from_arp(ip_address)
        if mac:
            logger.debug("%s: MAC obtained from ARP table: %s", ip_address, mac)
            snmp_operations_total.labels(operation="get_mac", result="success", reason="arp_fallback").inc()
            return mac

    snmp_operations_total.labels(
        operation="get_mac",
        result="success" if mac else "offline",
        reason="snmp" if mac else "not_found",
    ).inc()
    return mac
