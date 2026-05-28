from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from time import perf_counter

import httpx

from app.core.config import settings
from app.core.redis import get_redis
from app.observability.metrics import (
    network_bulk_operation_duration_seconds,
    network_discovery_devices_total,
    network_discovery_runs_total,
)
from app.services.net_inventory import parse_arp_table

logger = logging.getLogger(__name__)

DISCOVERY_TTL = 600
_DISCOVERY_TCP_SEMAPHORE = asyncio.Semaphore(max(settings.SCAN_TCP_CONCURRENCY, 1))
_DISCOVERY_HTTP_TIMEOUT = 2.0
_DISCOVERY_IDENTIFY_CONCURRENCY = 32

_PRINTER_HINTS = (
    "printer",
    "laserjet",
    "deskjet",
    "officejet",
    "ricoh",
    "xerox",
    "brother",
    "kyocera",
    "zebra",
    "epson",
    "canon",
    "mfp",
)

_SWITCH_HINTS = (
    "switch",
    "cisco ios",
    "catalyst",
    "nexus",
    "routeros",
    "mikrotik",
    "d-link",
    "arubaos",
    "procurve",
    "juniper",
    "ethernet",
    "bridge",
)


@dataclass
class DiscoveredNetworkDevice:
    ip: str
    mac: str | None = None
    open_ports: list[int] = field(default_factory=list)
    hostname: str | None = None
    model_info: str | None = None
    vendor: str | None = None
    device_kind: str | None = None
    is_known: bool = False
    known_device_id: str | None = None
    ip_changed: bool = False
    old_ip: str | None = None


def _progress_key(kind: str) -> str:
    return f"discover:{kind}:progress"


def _results_key(kind: str) -> str:
    return f"discover:{kind}:results"


def _lock_key(kind: str) -> str:
    return f"discover:{kind}:lock"


def _parse_subnets(subnet_str: str) -> list[str]:
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
                    raise ValueError(
                        f"Too many hosts to scan ({len(all_ips)}). Limit is {max_hosts}; split subnet ranges."
                    )
        except ValueError as exc:
            if "Too many hosts" in str(exc):
                raise
            logger.warning("Invalid discovery subnet: %s", part)
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
            logger.warning("Invalid discovery port: %s", raw)
            continue
        if not (1 <= port <= 65535):
            logger.warning("Discovery port out of range: %s", raw)
            continue
        if port in seen:
            continue
        seen.add(port)
        ports.append(port)
    return ports


async def _tcp_check(ip: str, port: int) -> bool:
    timeout = max(settings.SCAN_TCP_TIMEOUT, 0.1)
    retries = max(settings.SCAN_TCP_RETRIES, 0)
    for attempt in range(retries + 1):
        try:
            async with _DISCOVERY_TCP_SEMAPHORE:
                _, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=timeout)
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


def _normalize_vendor(value: str | None) -> str | None:
    if not value:
        return None
    low = value.lower()
    if "cisco" in low or "ios" in low or "catalyst" in low:
        return "cisco"
    if "d-link" in low or "dlink" in low:
        return "dlink"
    if "mikrotik" in low:
        return "mikrotik"
    if "hp" in low or "aruba" in low:
        return "aruba"
    return "generic"


async def _snmp_switch_fingerprint(ip: str, community: str = "public") -> dict[str, str | None]:
    try:
        from pysnmp.hlapi.asyncio import (
            CommunityData,
            ContextData,
            ObjectIdentity,
            ObjectType,
            SnmpEngine,
            UdpTransportTarget,
        )
        from pysnmp.hlapi.asyncio.cmdgen import getCmd
    except Exception:
        return {}
    try:
        target = UdpTransportTarget((ip, 161), timeout=2, retries=0)
    except Exception:
        return {}
    engine = SnmpEngine()
    oid_sys_descr = "1.3.6.1.2.1.1.1.0"
    oid_sys_name = "1.3.6.1.2.1.1.5.0"
    oid_sys_object_id = "1.3.6.1.2.1.1.2.0"
    try:
        err_indication, err_status, _, var_binds = await getCmd(
            engine,
            CommunityData(community, mpModel=1),
            target,
            ContextData(),
            ObjectType(ObjectIdentity(oid_sys_descr)),
            ObjectType(ObjectIdentity(oid_sys_name)),
            ObjectType(ObjectIdentity(oid_sys_object_id)),
        )
        if err_indication or err_status:
            return {}
        values: dict[str, str | None] = {"model_info": None, "hostname": None, "sys_object_id": None}
        for oid, val in var_binds:
            oid_str = str(oid)
            val_str = str(val).strip()
            if oid_sys_descr in oid_str:
                values["model_info"] = val_str
            elif oid_sys_name in oid_str:
                values["hostname"] = val_str
            elif oid_sys_object_id in oid_str:
                values["sys_object_id"] = val_str

        identity_text = " ".join(
            x for x in (values.get("model_info"), values.get("hostname"), values.get("sys_object_id")) if x
        ).lower()
        if any(h in identity_text for h in _PRINTER_HINTS):
            return {}
        if not any(h in identity_text for h in _SWITCH_HINTS):
            return {}
        return values
    except Exception:
        return {}


def _is_likely_iconbit_response(main_text: str, status_xml_text: str | None, now_text: str | None) -> bool:
    text = main_text.lower()
    if any(h in text for h in _PRINTER_HINTS):
        return False
    page_hints = "delete?file=" in text or "/play" in text or "/stop" in text or "iconbit" in text
    status_hints = False
    if status_xml_text:
        xml = status_xml_text.lower()
        status_hints = all(tag in xml for tag in ("<state>", "<position>", "<duration>"))
    now_hints = False
    if now_text:
        now_l = now_text.lower()
        now_hints = "<b>" in now_l or "now playing" in now_l or "playing" in now_l
    return page_hints or status_hints or now_hints


async def _iconbit_fingerprint(ip: str) -> dict[str, str | None]:
    base = f"http://{ip}:8081"
    auth = ("admin", "admin")
    try:
        async with httpx.AsyncClient(timeout=_DISCOVERY_HTTP_TIMEOUT, follow_redirects=True, auth=auth) as client:
            main = await client.get(base)
            if main.status_code != 200:
                return {}
            text = main.text[:5000]
            status_xml = await client.get(f"{base}/status.xml")
            now = await client.get(f"{base}/now")
            if not _is_likely_iconbit_response(
                text,
                status_xml.text[:5000] if status_xml.status_code == 200 else None,
                now.text[:5000] if now.status_code == 200 else None,
            ):
                return {}
            model_match = re.search(r"<title>([^<]+)</title>", text, re.IGNORECASE)
            model = model_match.group(1).strip() if model_match else "Iconbit"
            return {"model_info": model, "device_kind": "iconbit"}
    except Exception:
        return {}
    return {}


async def _update_progress(
    kind: str, status: str, scanned: int, total: int, found: int, message: str | None = None
) -> None:
    r = await get_redis()
    payload = {"status": status, "scanned": scanned, "total": total, "found": found, "message": message}
    await r.setex(_progress_key(kind), DISCOVERY_TTL, json.dumps(payload))


async def run_discovery_scan(kind: str, subnet: str, ports_str: str, known_devices: list[dict]) -> list[dict]:
    if kind not in {"iconbit", "switch"}:
        raise ValueError("Unsupported discovery kind")
    r = await get_redis()
    lock_key = _lock_key(kind)
    if await r.exists(lock_key):
        raise RuntimeError("Discovery scan already in progress")
    await r.setex(lock_key, 300, "1")
    started = perf_counter()
    try:
        all_ips = _parse_subnets(subnet)
        if not all_ips:
            raise ValueError("No valid IPs to scan")
        ports = _parse_ports(ports_str)
        if not ports:
            raise ValueError("No valid ports configured")

        known_by_ip = {d["ip_address"]: d for d in known_devices if d.get("ip_address")}
        known_by_mac = {d["mac_address"].lower(): d for d in known_devices if d.get("mac_address")}

        await _update_progress(kind, "running", 0, len(all_ips), 0)
        devices: list[DiscoveredNetworkDevice] = []
        batch_size = 64
        scanned = 0
        for i in range(0, len(all_ips), batch_size):
            batch = all_ips[i : i + batch_size]
            results = await asyncio.gather(*[_check_ports(ip, ports) for ip in batch])
            for ip, open_ports in zip(batch, results):
                if not open_ports:
                    continue
                device = DiscoveredNetworkDevice(ip=ip, open_ports=open_ports)
                if ip in known_by_ip:
                    device.is_known = True
                    device.known_device_id = str(known_by_ip[ip]["id"])
                devices.append(device)
            scanned += len(batch)
            await _update_progress(kind, "running", scanned, len(all_ips), len(devices))

        if devices:
            await _update_progress(
                kind, "running", len(all_ips), len(all_ips), len(devices), "Идентификация устройств…"
            )
            if kind == "iconbit":
                semaphore = asyncio.Semaphore(_DISCOVERY_IDENTIFY_CONCURRENCY)

                async def _identify_iconbit(dev: DiscoveredNetworkDevice) -> None:
                    if 8081 not in dev.open_ports:
                        return
                    async with semaphore:
                        info = await _iconbit_fingerprint(dev.ip)
                    if not info:
                        return
                    dev.device_kind = "iconbit"
                    dev.model_info = info.get("model_info")

                await asyncio.gather(*[_identify_iconbit(dev) for dev in devices])
            else:
                semaphore = asyncio.Semaphore(_DISCOVERY_IDENTIFY_CONCURRENCY)

                async def _identify_switch(dev: DiscoveredNetworkDevice) -> None:
                    async with semaphore:
                        info = await _snmp_switch_fingerprint(dev.ip)
                    if not info:
                        return
                    dev.hostname = info.get("hostname")
                    dev.model_info = info.get("model_info")
                    dev.device_kind = "switch"
                    dev.vendor = _normalize_vendor(dev.model_info)

                await asyncio.gather(*[_identify_switch(dev) for dev in devices])

            # Best-effort ARP enrich and known by MAC.
            arp = await asyncio.to_thread(parse_arp_table)
            for dev in devices:
                mac = arp.get(dev.ip)
                if mac:
                    dev.mac = mac
                    known = known_by_mac.get(mac.lower())
                    if known and not dev.is_known:
                        dev.is_known = True
                        dev.known_device_id = str(known["id"])
                        dev.ip_changed = True
                        dev.old_ip = known.get("ip_address")

        # Keep only confidently identified target devices.
        if kind == "iconbit":
            devices = [d for d in devices if d.device_kind == "iconbit"]
        else:
            devices = [d for d in devices if d.device_kind == "switch"]

        result = [asdict(d) for d in devices]
        await r.setex(_results_key(kind), DISCOVERY_TTL, json.dumps(result))
        await _update_progress(kind, "done", len(all_ips), len(all_ips), len(result))
        network_discovery_runs_total.labels(kind=kind, result="success").inc()
        network_discovery_devices_total.labels(kind=kind).inc(len(result))
        return result
    except Exception:
        network_discovery_runs_total.labels(kind=kind, result="error").inc()
        raise
    finally:
        await r.delete(lock_key)
        network_bulk_operation_duration_seconds.labels(operation=f"{kind}_discovery_scan").observe(
            max(perf_counter() - started, 0)
        )
        logger.info("Discovery scan '%s' completed in %.2fs", kind, max(perf_counter() - started, 0))


async def get_discovery_progress(kind: str) -> dict:
    r = await get_redis()
    data = await r.get(_progress_key(kind))
    if data:
        return json.loads(data)
    return {"status": "idle", "scanned": 0, "total": 0, "found": 0, "message": None}


async def get_discovery_results(kind: str) -> list[dict]:
    r = await get_redis()
    data = await r.get(_results_key(kind))
    if data:
        return json.loads(data)
    return []
