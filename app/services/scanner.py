"""
Network scanner for discovering printers on the local network.

Works universally from Docker bridge network on Windows, macOS, and Linux.
TCP port scanning and SNMP identification work through Docker NAT.
MAC address resolution is best-effort (requires host network on Linux).
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import socket
from dataclasses import asdict, dataclass, field
from time import perf_counter

from app.core.config import settings
from app.core.redis import get_redis
from app.observability.metrics import (
    scanner_devices_found_total,
    scanner_duration_seconds,
    scanner_runs_total,
)
from app.services.net_inventory import parse_arp_table

logger = logging.getLogger(__name__)

SCAN_KEY_PROGRESS = "scan:progress"
SCAN_KEY_RESULTS = "scan:results"
SCAN_KEY_LOCK = "scan:lock"
SCAN_TTL = 600
_SCAN_TCP_SEMAPHORE = asyncio.Semaphore(max(settings.SCAN_TCP_CONCURRENCY, 1))


@dataclass
class DiscoveredDevice:
    ip: str
    mac: str | None = None
    open_ports: list[int] = field(default_factory=list)
    hostname: str | None = None
    is_known: bool = False
    known_printer_id: str | None = None
    ip_changed: bool = False
    old_ip: str | None = None


class SubnetLimitExceeded(ValueError):
    """Raised when subnet expansion exceeds configured host limit."""


async def _tcp_check(ip: str, port: int) -> bool:
    timeout = max(settings.SCAN_TCP_TIMEOUT, 0.1)
    retries = max(settings.SCAN_TCP_RETRIES, 0)
    for attempt in range(retries + 1):
        try:
            async with _SCAN_TCP_SEMAPHORE:
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection(ip, port),
                    timeout=timeout,
                )
                writer.close()
                await writer.wait_closed()
                return True
        except (TimeoutError, OSError):
            if attempt < retries:
                await asyncio.sleep(0.05 * (attempt + 1))
    return False


async def _check_ports(ip: str, ports: list[int]) -> list[int]:
    tasks = [_tcp_check(ip, port) for port in ports]
    results = await asyncio.gather(*tasks)
    return [port for port, is_open in zip(ports, results) if is_open]


@dataclass
class SnmpInfo:
    hostname: str | None = None
    mac: str | None = None


def _snmp_query_sync(ip: str) -> SnmpInfo:
    """Query sysDescr + ifPhysAddress via SNMP. Each call gets its own event loop.

    Sequential execution is intentional: pysnmp's UDP transport
    has global state that causes failures under concurrency.
    """
    import warnings

    warnings.filterwarnings("ignore", message=".*pysnmp-lextudio.*")

    OID_SYS_DESCR = "1.3.6.1.2.1.1.1.0"
    OID_IF_PHYS_ADDR = "1.3.6.1.2.1.2.2.1.6"

    async def _query() -> SnmpInfo:
        from pysnmp.hlapi.asyncio import (
            CommunityData,
            ContextData,
            ObjectIdentity,
            ObjectType,
            SnmpEngine,
            UdpTransportTarget,
        )
        from pysnmp.hlapi.asyncio.cmdgen import getCmd, walkCmd

        info = SnmpInfo()
        engine = SnmpEngine()
        target = UdpTransportTarget((ip, 161), timeout=2, retries=0)
        comm = CommunityData("public")
        ctx = ContextData()

        # sysDescr
        result = await getCmd(
            engine,
            comm,
            target,
            ctx,
            ObjectType(ObjectIdentity(OID_SYS_DESCR)),
        )
        error_indication, _, _, var_binds = result
        if not error_indication and var_binds:
            val = str(var_binds[0][1])
            if val:
                info.hostname = val

        # ifPhysAddress (walk to find first non-empty 6-byte MAC)
        try:
            async for err, _, _, vb in walkCmd(
                engine,
                comm,
                target,
                ctx,
                ObjectType(ObjectIdentity(OID_IF_PHYS_ADDR)),
            ):
                if err:
                    break
                for _, val in vb:
                    if hasattr(val, "asOctets"):
                        octets = val.asOctets()
                        if len(octets) == 6 and any(b != 0 for b in octets):
                            info.mac = ":".join(f"{b:02x}" for b in octets)
                            raise StopAsyncIteration
        except StopAsyncIteration:
            pass

        return info

    try:
        return asyncio.run(_query())
    except Exception:
        return SnmpInfo()


def _snmp_batch(ips: list[str]) -> dict[str, SnmpInfo]:
    """Query SNMP info for a list of IPs sequentially (~0.1s per device)."""
    results: dict[str, SnmpInfo] = {}
    for ip in ips:
        results[ip] = _snmp_query_sync(ip)
    return results


async def _update_progress(status: str, scanned: int, total: int, found: int, message: str | None = None) -> None:
    r = await get_redis()
    progress = {
        "status": status,
        "scanned": scanned,
        "total": total,
        "found": found,
        "message": message,
    }
    await r.setex(SCAN_KEY_PROGRESS, SCAN_TTL, json.dumps(progress))


def _parse_subnets(subnet_str: str) -> list[str]:
    """Parse comma-separated subnets or IP ranges."""
    all_ips: list[str] = []
    seen: set[str] = set()
    max_hosts = max(settings.SCAN_MAX_HOSTS, 1)
    for part in subnet_str.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            network = ipaddress.ip_network(part, strict=False)
            for ip in network.hosts():
                ip_str = str(ip)
                if ip_str in seen:
                    continue
                seen.add(ip_str)
                all_ips.append(ip_str)
                if len(all_ips) > max_hosts:
                    raise SubnetLimitExceeded(
                        f"Too many hosts to scan ({len(all_ips)}). "
                        f"Limit is {max_hosts}; split SCAN_SUBNET into smaller ranges."
                    )
        except SubnetLimitExceeded:
            raise
        except ValueError:
            logger.warning("Invalid subnet or subnet limit exceeded: %s", part)
    return all_ips


def _parse_ports(ports_str: str) -> list[int]:
    ports: list[int] = []
    seen: set[int] = set()
    for raw in ports_str.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            port = int(raw)
        except ValueError:
            logger.warning("Invalid scan port: %s", raw)
            continue
        if not (1 <= port <= 65535):
            logger.warning("Scan port out of range: %s", raw)
            continue
        if port in seen:
            continue
        seen.add(port)
        ports.append(port)
    return ports


async def scan_subnet(subnet: str, ports_str: str, known_printers: list[dict]) -> list[dict]:
    """
    Scan subnet(s) for devices with open printer ports.
    Supports comma-separated subnets: "10.10.98.0/24, 10.10.99.0/24"
    """
    r = await get_redis()

    if await r.exists(SCAN_KEY_LOCK):
        raise RuntimeError("Scan already in progress")

    await r.setex(SCAN_KEY_LOCK, 300, "1")

    started = perf_counter()
    try:
        all_ips = _parse_subnets(subnet)
        if not all_ips:
            raise ValueError(f"No valid IPs in subnet: {subnet}")

        total = len(all_ips)
        ports = _parse_ports(ports_str)
        if not ports:
            raise ValueError("No valid scan ports configured")

        await _update_progress("running", 0, total, 0)

        known_by_ip = {p["ip_address"]: p for p in known_printers}
        known_by_mac = {}
        for p in known_printers:
            if p.get("mac_address"):
                known_by_mac[p["mac_address"].lower()] = p

        devices: list[DiscoveredDevice] = []
        batch_size = 50
        scanned = 0

        for i in range(0, total, batch_size):
            batch = all_ips[i : i + batch_size]
            tasks = [_check_ports(ip, ports) for ip in batch]
            results = await asyncio.gather(*tasks)

            for ip, open_ports in zip(batch, results):
                if open_ports:
                    dev = DiscoveredDevice(ip=ip, open_ports=open_ports)
                    if ip in known_by_ip:
                        dev.is_known = True
                        dev.known_printer_id = str(known_by_ip[ip]["id"])
                    devices.append(dev)

            scanned += len(batch)
            await _update_progress("running", min(scanned, total), total, len(devices))

        # SNMP identification + MAC detection for devices with printer ports
        printer_ports = {9100, 631}
        snmp_candidates = [d for d in devices if printer_ports & set(d.open_ports)]
        logger.info("SNMP: %d candidates out of %d found devices", len(snmp_candidates), len(devices))

        if snmp_candidates:
            await _update_progress("running", total, total, len(devices), "Идентификация устройств (SNMP)…")
            snmp_results = await asyncio.to_thread(_snmp_batch, [d.ip for d in snmp_candidates])
            identified = 0
            for dev in snmp_candidates:
                info = snmp_results.get(dev.ip)
                if info:
                    if info.hostname:
                        dev.hostname = info.hostname
                        identified += 1
                    if info.mac:
                        dev.mac = info.mac
                        if not dev.is_known and info.mac in known_by_mac:
                            kp = known_by_mac[info.mac]
                            dev.ip_changed = True
                            dev.old_ip = kp["ip_address"]
                            dev.known_printer_id = str(kp["id"])
            logger.info("SNMP done: %d/%d identified", identified, len(snmp_candidates))

        # ARP table for remaining devices without SNMP MAC (best-effort)
        arp = await asyncio.to_thread(parse_arp_table)
        for dev in devices:
            if dev.mac:
                continue
            mac = arp.get(dev.ip)
            if mac:
                dev.mac = mac
                if not dev.is_known and mac in known_by_mac:
                    kp = known_by_mac[mac]
                    dev.ip_changed = True
                    dev.old_ip = kp["ip_address"]
                    dev.known_printer_id = str(kp["id"])

        result_dicts = [asdict(d) for d in devices]
        progress = {
            "status": "done",
            "scanned": total,
            "total": total,
            "found": len(devices),
            "message": None,
        }
        await r.setex(SCAN_KEY_PROGRESS, SCAN_TTL, json.dumps(progress))
        await r.setex(SCAN_KEY_RESULTS, SCAN_TTL, json.dumps(result_dicts))
        scanner_runs_total.labels(result="success").inc()
        scanner_devices_found_total.inc(len(devices))
        return result_dicts

    except Exception as e:
        logger.exception("Scan failed")
        await _update_progress("error", 0, 0, 0, str(e))
        scanner_runs_total.labels(result="error").inc()
        raise
    finally:
        scanner_duration_seconds.observe(max(perf_counter() - started, 0))
        await r.delete(SCAN_KEY_LOCK)


async def get_scan_progress() -> dict:
    r = await get_redis()
    data = await r.get(SCAN_KEY_PROGRESS)
    if data:
        return json.loads(data)
    return {"status": "idle", "scanned": 0, "total": 0, "found": 0, "message": None}


async def get_scan_results() -> list[dict]:
    r = await get_redis()
    data = await r.get(SCAN_KEY_RESULTS)
    if data:
        return json.loads(data)
    return []


def _reverse_dns_sync(ip: str) -> str | None:
    try:
        host, _, _ = socket.gethostbyaddr(ip)
        return host
    except OSError:
        return None


async def smart_probe_network(subnet: str, ports_str: str) -> list[dict]:
    """
    Lightweight generic scanner for smart network discovery.
    It does not write scan progress/results to Redis keys used by printer scanner.
    """
    all_ips = _parse_subnets(subnet)
    if not all_ips:
        return []
    ports = _parse_ports(ports_str)
    if not ports:
        return []

    devices: list[DiscoveredDevice] = []
    batch_size = 64
    for i in range(0, len(all_ips), batch_size):
        batch = all_ips[i : i + batch_size]
        results = await asyncio.gather(*[_check_ports(ip, ports) for ip in batch])
        for ip, open_ports in zip(batch, results):
            if open_ports:
                devices.append(DiscoveredDevice(ip=ip, open_ports=open_ports))

    if not devices:
        return []

    # Resolve hostnames best-effort in parallel.
    hostnames = await asyncio.gather(*[asyncio.to_thread(_reverse_dns_sync, d.ip) for d in devices])
    for device, hostname in zip(devices, hostnames):
        device.hostname = hostname

    return [asdict(item) for item in devices]
