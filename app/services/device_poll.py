"""Polling service for media players and generic network devices.

Collects: online status, hostname, OS info, uptime, MAC address, open ports.
Uses SNMP where available, with TCP port scan and ARP fallback.
Supports NetBIOS name resolution for Windows hosts.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import platform
import re as _re
import socket
import struct
import time
import warnings
from dataclasses import dataclass, field

warnings.filterwarnings("ignore", message=".*pysnmp-lextudio.*")

from pysnmp.hlapi.asyncio import (  # noqa: E402
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
)
from pysnmp.hlapi.asyncio.cmdgen import getCmd, walkCmd  # noqa: E402

from app.observability.metrics import media_player_ops_total  # noqa: E402

logger = logging.getLogger(__name__)
_RESOLVE_WARN_COOLDOWN_SECONDS = 300.0
_RESOLVE_WARN_LAST_SEEN: dict[str, float] = {}
_RESOLVE_CACHE_SECONDS = 300.0
_RESOLVE_CACHE: dict[str, tuple[float, str | None]] = {}

SNMP_TIMEOUT = 3
SNMP_RETRIES = 1

OID_SYS_DESCR = "1.3.6.1.2.1.1.1.0"
OID_SYS_NAME = "1.3.6.1.2.1.1.5.0"
OID_SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
OID_IF_PHYS_ADDR = "1.3.6.1.2.1.2.2.1.6"

SCAN_PORTS = [22, 80, 135, 139, 443, 445, 554, 3389, 5405, 8080, 8081, 9090]
TCP_TIMEOUT = 2.0
_PORT_SCAN_SEMAPHORE = asyncio.Semaphore(64)
_MAX_NETBIOS_TARGETS = 2048
_PING_SWEEP_CONCURRENCY = 128


def _ping_command(ip: str) -> list[str]:
    system = platform.system()
    if system == "Windows":
        return ["ping", "-n", "1", "-w", "1000", ip]
    if system == "Darwin":
        return ["ping", "-c", "1", "-W", "1000", ip]
    return ["ping", "-c", "1", "-W", "1", ip]


@dataclass
class DeviceStatus:
    is_online: bool = False
    hostname: str | None = None
    os_info: str | None = None
    uptime: str | None = None
    mac_address: str | None = None
    open_ports: list[int] = field(default_factory=list)


def _format_uptime(ticks: int) -> str:
    seconds = ticks // 100
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}д")
    if hours:
        parts.append(f"{hours}ч")
    parts.append(f"{minutes}м")
    return " ".join(parts)


async def _check_port(ip: str, port: int) -> int | None:
    try:
        async with _PORT_SCAN_SEMAPHORE:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port),
                timeout=TCP_TIMEOUT,
            )
            writer.close()
            await writer.wait_closed()
            return port
    except (TimeoutError, OSError):
        return None


async def _scan_ports(ip: str) -> list[int]:
    tasks = [_check_port(ip, port) for port in SCAN_PORTS]
    results = await asyncio.gather(*tasks)
    return sorted(p for p in results if p is not None)


async def _get_snmp_info(ip: str, community: str = "public") -> dict:
    """Retrieve sysDescr, sysName, sysUpTime via SNMP GET."""
    engine = SnmpEngine()
    try:
        target = UdpTransportTarget((ip, 161), timeout=SNMP_TIMEOUT, retries=SNMP_RETRIES)
    except Exception:
        return {}

    comm = CommunityData(community)
    result = {}

    try:
        err_indication, err_status, _, var_binds = await getCmd(
            engine,
            comm,
            target,
            ContextData(),
            ObjectType(ObjectIdentity(OID_SYS_DESCR)),
            ObjectType(ObjectIdentity(OID_SYS_NAME)),
            ObjectType(ObjectIdentity(OID_SYS_UPTIME)),
        )
        if err_indication or err_status:
            return {}

        for oid, val in var_binds:
            oid_str = str(oid)
            val_str = str(val).strip()
            if not val_str:
                continue
            if OID_SYS_DESCR in oid_str:
                result["os_info"] = val_str[:255]
            elif OID_SYS_NAME in oid_str:
                result["hostname"] = val_str[:255]
            elif OID_SYS_UPTIME in oid_str:
                try:
                    ticks = int(val)
                    result["uptime"] = _format_uptime(ticks)
                except (ValueError, TypeError):
                    result["uptime"] = val_str
    except Exception as e:
        logger.debug("SNMP GET failed for %s: %s", ip, e)

    return result


async def _get_snmp_mac(ip: str, community: str = "public") -> str | None:
    engine = SnmpEngine()
    try:
        target = UdpTransportTarget((ip, 161), timeout=SNMP_TIMEOUT, retries=SNMP_RETRIES)
    except Exception:
        return None

    comm = CommunityData(community)
    try:
        async for err, _, _, vb in walkCmd(
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


def _get_mac_from_arp(ip: str) -> str | None:
    import subprocess

    try:
        subprocess.run(
            _ping_command(ip),
            capture_output=True,
            timeout=3,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    try:
        with open("/proc/net/arp") as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                if len(parts) >= 4 and parts[0] == ip:
                    mac = parts[3].lower()
                    if mac != "00:00:00:00:00:00" and len(mac) == 17:
                        return mac
    except (FileNotFoundError, PermissionError):
        pass

    try:
        out = subprocess.run(
            ["ip", "neigh", "show", ip],
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


def _netbios_encode_name(name: str) -> bytes:
    """Encode a NetBIOS name using first-level encoding (RFC 1001)."""
    padded = name.upper().ljust(16, " ")[:16]
    encoded = bytearray()
    for ch in padded:
        b = ord(ch)
        encoded.append(0x41 + (b >> 4))
        encoded.append(0x41 + (b & 0x0F))
    return bytes([32]) + bytes(encoded) + b"\x00"


def _netbios_query_packet(name: str) -> bytes:
    """Build a NetBIOS Name Query Request packet."""
    header = struct.pack(
        ">HHHHHH",
        0x0001,  # transaction id
        0x0110,  # flags: recursion desired, broadcast
        1,
        0,
        0,
        0,  # 1 question, 0 answers
    )
    qname = _netbios_encode_name(name)
    qtype_class = struct.pack(">HH", 0x0020, 0x0001)  # NB, IN
    return header + qname + qtype_class


def _netbios_parse_response(data: bytes) -> str | None:
    """Parse IP address from a NetBIOS Name Query Response."""
    if len(data) < 60:
        return None
    try:
        ans_count = struct.unpack(">H", data[6:8])[0]
        if ans_count == 0:
            return None
        offset = 12
        # skip question name
        while offset < len(data):
            length = data[offset]
            if length == 0:
                offset += 1
                break
            offset += 1 + length
        offset += 4  # qtype + qclass
        # skip answer name (may be pointer)
        if offset < len(data) and (data[offset] & 0xC0) == 0xC0:
            offset += 2
        else:
            while offset < len(data):
                length = data[offset]
                if length == 0:
                    offset += 1
                    break
                offset += 1 + length
        # type(2) + class(2) + ttl(4) + rdlength(2) = 10
        offset += 10
        # rdata: flags(2) + ip(4)
        offset += 2
        if offset + 4 <= len(data):
            return socket.inet_ntoa(data[offset : offset + 4])
    except Exception:
        pass
    return None


def _netbios_resolve(name: str, subnets: list[str] | None = None) -> str | None:
    """Resolve a Windows hostname via NetBIOS name query.

    Uses unicast queries to each IP in known subnets (broadcasts
    don't cross Docker bridge networks).  UDP is connectionless, so
    we blast packets to all hosts and wait for the first response.
    """
    if subnets is None:
        raw = os.environ.get("SCAN_SUBNET", "")
        subnets = [s.strip() for s in raw.split(",") if s.strip()]

    targets: list[str] = []
    for subnet_str in subnets:
        try:
            net = ipaddress.IPv4Network(subnet_str, strict=False)
            targets.extend(str(h) for h in net.hosts())
        except ValueError:
            continue
    if len(targets) > _MAX_NETBIOS_TARGETS:
        logger.warning(
            "NetBIOS target list too large (%d), truncating to %d for safety",
            len(targets),
            _MAX_NETBIOS_TARGETS,
        )
        targets = targets[:_MAX_NETBIOS_TARGETS]

    if not targets:
        return None

    packet = _netbios_query_packet(name)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)

    try:
        for ip in targets:
            try:
                sock.sendto(packet, (ip, 137))
            except OSError:
                pass

        logger.debug("NetBIOS: sent query for '%s' to %d hosts", name, len(targets))

        import select as _select
        import time

        end = time.monotonic() + 3.0
        while time.monotonic() < end:
            remaining = end - time.monotonic()
            if remaining <= 0:
                break
            ready, _, _ = _select.select([sock], [], [], min(remaining, 0.5))
            if ready:
                try:
                    data, (resp_ip, _) = sock.recvfrom(1024)
                    parsed_ip = _netbios_parse_response(data)
                    if parsed_ip:
                        logger.info("NetBIOS resolved %s -> %s (unicast from %s)", name, parsed_ip, resp_ip)
                        return parsed_ip
                except OSError:
                    pass
    finally:
        sock.close()

    return None


def _resolve_host(address: str) -> str | None:
    """Resolve hostname to IP via DNS then NetBIOS fallback."""
    if _re.match(r"^(\d{1,3}\.){3}\d{1,3}$", address):
        return address

    cached = _RESOLVE_CACHE.get(address)
    now = time.monotonic()
    if cached and now - cached[0] < _RESOLVE_CACHE_SECONDS:
        return cached[1]

    # 1. DNS
    try:
        resolved = socket.gethostbyname(address)
        _RESOLVE_CACHE[address] = (time.monotonic(), resolved)
        return resolved
    except socket.gaierror:
        pass

    if "." not in address:
        for suffix in [".local", ".lan"]:
            try:
                resolved = socket.gethostbyname(address + suffix)
                _RESOLVE_CACHE[address] = (time.monotonic(), resolved)
                return resolved
            except socket.gaierror:
                pass

    # 2. NetBIOS (for Windows hostnames)
    ip = _netbios_resolve(address)
    if ip:
        _RESOLVE_CACHE[address] = (time.monotonic(), ip)
        return ip

    last = _RESOLVE_WARN_LAST_SEEN.get(address, 0.0)
    if now - last >= _RESOLVE_WARN_COOLDOWN_SECONDS:
        _RESOLVE_WARN_LAST_SEEN[address] = now
        logger.warning("Cannot resolve hostname: %s", address)
    _RESOLVE_CACHE[address] = (now, None)
    return None


async def poll_device(address: str, community: str = "public") -> DeviceStatus:
    """Poll a network device for status information.

    ``address`` can be an IP address or hostname.
    """
    status = DeviceStatus()

    ip = await asyncio.to_thread(_resolve_host, address)
    if not ip:
        media_player_ops_total.labels(operation="poll_device", result="error").inc()
        status.is_online = False
        return status

    ports_task = _scan_ports(ip)
    snmp_task = _get_snmp_info(ip, community)
    mac_task = _get_snmp_mac(ip, community)

    open_ports, snmp_info, mac = await asyncio.gather(
        ports_task,
        snmp_task,
        mac_task,
    )

    status.open_ports = open_ports
    status.is_online = bool(open_ports) or bool(snmp_info)

    if snmp_info:
        status.hostname = snmp_info.get("hostname")
        status.os_info = snmp_info.get("os_info")
        status.uptime = snmp_info.get("uptime")

    if not status.hostname and ip != address:
        status.hostname = address

    status.mac_address = mac
    if not mac:
        arp_mac = await asyncio.to_thread(_get_mac_from_arp, ip)
        if arp_mac:
            status.mac_address = arp_mac

    media_player_ops_total.labels(
        operation="poll_device",
        result="success" if status.is_online else "offline",
    ).inc()
    return status


def _check_arp_for_mac(target_mac: str) -> str | None:
    """Check current ARP table for a MAC address (no scanning)."""
    import subprocess

    target_mac = target_mac.lower().strip()

    try:
        with open("/proc/net/arp") as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                if len(parts) >= 4 and parts[3].lower() == target_mac:
                    return parts[0]
    except (FileNotFoundError, PermissionError):
        pass

    try:
        out = subprocess.run(
            ["ip", "neigh"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
        for line in out.strip().split("\n"):
            if target_mac in line.lower():
                parts = line.split()
                if parts:
                    return parts[0]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


async def _async_ping(ip: str) -> None:
    """Fire-and-forget async ping to populate ARP cache."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *_ping_command(ip),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=2)
    except (TimeoutError, OSError):
        pass


async def find_device_by_mac(mac: str, subnets: list[str] | None = None) -> str | None:
    results = await find_devices_by_macs([mac], subnets=subnets)
    return results.get(mac.lower().strip())


def _arp_table_mac_to_ip() -> dict[str, str]:
    """Build MAC->IP map from ARP/neigh tables."""
    import subprocess

    out: dict[str, str] = {}
    try:
        with open("/proc/net/arp") as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                if len(parts) >= 4:
                    ip = parts[0]
                    mac = parts[3].lower()
                    if mac != "00:00:00:00:00:00" and len(mac) == 17:
                        out[mac] = ip
    except (FileNotFoundError, PermissionError):
        pass

    try:
        neigh = subprocess.run(
            ["ip", "neigh"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
        for line in neigh.strip().split("\n"):
            parts = line.split()
            if "lladdr" in parts:
                ip = parts[0]
                idx = parts.index("lladdr")
                if idx + 1 < len(parts):
                    mac = parts[idx + 1].lower()
                    if len(mac) == 17:
                        out[mac] = ip
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return out


async def find_devices_by_macs(macs: list[str], subnets: list[str] | None = None) -> dict[str, str]:
    """Find a device's current IP by its MAC address.

    Optimized for batch lookups:
    1. Checks ARP table once for all MACs.
    2. If unresolved, does bounded ping sweep once, rechecking ARP in batches.
    """
    targets = {m.lower().strip() for m in macs if m and m.strip()}
    if not targets:
        return {}
    found: dict[str, str] = {}

    # Quick check — maybe targets are already in ARP.
    arp_map = await asyncio.to_thread(_arp_table_mac_to_ip)
    for mac in targets:
        ip = arp_map.get(mac)
        if ip:
            found[mac] = ip
    if len(found) == len(targets):
        media_player_ops_total.labels(operation="find_by_mac", result="success").inc(len(found))
        return found

    if subnets is None:
        raw = os.environ.get("SCAN_SUBNET", "")
        subnets = [s.strip() for s in raw.split(",") if s.strip()]

    hosts: list[str] = []
    for subnet_str in subnets:
        try:
            net = ipaddress.IPv4Network(subnet_str, strict=False)
            hosts.extend(str(h) for h in net.hosts())
        except ValueError:
            continue

    if not hosts:
        media_player_ops_total.labels(operation="find_by_mac", result="error").inc()
        return found

    # Ping sweep in bounded batches to avoid self-induced packet storms.
    batch_size = _PING_SWEEP_CONCURRENCY
    for i in range(0, len(hosts), batch_size):
        batch = hosts[i : i + batch_size]
        await asyncio.gather(*[_async_ping(h) for h in batch])
        arp_map = await asyncio.to_thread(_arp_table_mac_to_ip)
        for mac in targets - found.keys():
            ip = arp_map.get(mac)
            if ip:
                found[mac] = ip
        if len(found) == len(targets):
            break

    if found:
        media_player_ops_total.labels(operation="find_by_mac", result="success").inc(len(found))
    if len(found) < len(targets):
        media_player_ops_total.labels(operation="find_by_mac", result="offline").inc(len(targets) - len(found))
    return found


def poll_device_sync(address: str, community: str = "public") -> DeviceStatus:
    """Synchronous wrapper for poll_device.

    ``address`` can be an IP address or hostname.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, poll_device(address, community)).result()
    else:
        return asyncio.run(poll_device(address, community))
