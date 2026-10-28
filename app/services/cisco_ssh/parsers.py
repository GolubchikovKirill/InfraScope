"""Parsers for Cisco IOS command output. Pure functions: text in, records out."""

from __future__ import annotations

import re

from .models import APInfo, CameraPortInfo, InterfaceStatusRow

_INTERFACE_STATUS_RE = re.compile(
    r"^(?P<port>\S+)\s{2,}(?P<name>\S.*?)?\s{2,}"
    r"(?P<status>connected|notconnect|disabled|err-disabled|monitor|inactive)\s+"
    r"(?P<vlan>\S+)\s+(?P<duplex>\S+)\s+(?P<speed>\S+)\s+(?P<type>\S+)\s*$"
)


def parse_interface_status_table(output: str) -> list[InterfaceStatusRow]:
    """Parse 'show interfaces status' into structured rows.

    Uses double-space-delimited columns rather than splitting on whitespace
    or counting tokens from the end of the line: the Name column is
    fixed-width but frequently empty, so a port with no description has one
    fewer whitespace-separated token than one with a description - counting
    from the end silently drops every undescribed port, which in practice
    is most of them.
    """
    rows: list[InterfaceStatusRow] = []
    for raw_line in output.splitlines():
        line = raw_line.rstrip()
        if not line or line.lower().startswith("port ") or line.startswith("---"):
            continue
        m = _INTERFACE_STATUS_RE.match(line)
        if not m:
            continue
        name = (m.group("name") or "").strip()
        rows.append(
            InterfaceStatusRow(
                port=m.group("port"),
                name=name if name and name != "--" else None,
                status=m.group("status"),
                vlan_text=m.group("vlan"),
                duplex_text=m.group("duplex"),
                speed_text=m.group("speed"),
                media_type=m.group("type"),
            )
        )
    return rows


def _parse_ports_on_vlans(status_output: str, vlans: set[int]) -> list[CameraPortInfo]:
    ports: list[CameraPortInfo] = []
    for row in parse_interface_status_table(status_output):
        if not row.vlan_text.isdigit() or int(row.vlan_text) not in vlans:
            continue
        ports.append(
            CameraPortInfo(
                port=row.port,
                vlan=int(row.vlan_text),
                oper_status=row.status,
                description=row.name,
            )
        )
    return ports


def _enrich_camera_poe(ports: list[CameraPortInfo], poe_output: str) -> None:
    poe_by_port: dict[str, dict] = {}
    for line in poe_output.split("\n"):
        m = re.match(r"\s*(\S+)\s+\S+\s+(\S+)\s+([\d.]+)\s+", line)
        if m:
            port_key = _normalize_port(m.group(1))
            poe_by_port[port_key] = {"status": m.group(2), "power": m.group(3) + "W"}

    for cam in ports:
        port_key = _normalize_port(cam.port)
        if port_key in poe_by_port:
            cam.poe_status = poe_by_port[port_key].get("status")
            cam.poe_power = poe_by_port[port_key].get("power")


def _parse_arp_mac_to_ip(arp_output: str) -> dict[str, str]:
    mac_to_ip: dict[str, str] = {}
    for line in arp_output.split("\n"):
        m = re.search(
            r"(\d+\.\d+\.\d+\.\d+)\s+\S+\s+"
            r"([0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4})",
            line,
        )
        if m:
            mac = _format_mac(m.group(2).lower())
            mac_to_ip[mac] = m.group(1)
    return mac_to_ip


_AP_PLATFORM_PATTERNS = re.compile(
    # AIR-CT... is a Wireless LAN Controller, not an access point - it just
    # shares the "AIR-" prefix with real AP models (AIR-CAP..., AIR-LAP...,
    # AIR-AP...). Confirmed on A22: a 5508 controller's two uplinks were
    # being counted as APs (no MAC ever resolved for them, so they were
    # silently filtered out downstream, but they still polluted CDP counts
    # and logs).
    r"AIR-(?!CT)|[Aa]ironet|[Cc]9120|[Cc]9130|[Cc]9115|[Cc]9105|[Cc]1560"
    r"|[Cc]isco\s+AP|[Ww]ireless|Trans-Bridge",
)

# A Cisco AP's own CDP device ID defaults to "AP" + its MAC in dotted-hex
# form (e.g. "APecbd.1df9.7ba0") whenever it hasn't been given a custom
# hostname. Confirmed on A8: CDP correctly reported this AP every scan, but
# `show mac address-table` didn't always have a current entry for its port
# (CAM entries age out well before CDP's own holdtime), so the AP's MAC came
# back empty and it was silently dropped downstream by callers that filter
# on `ap.mac_address` being set - identical to being reported as completely
# missing, even though CDP saw it fine.
_AP_NAME_MAC_RE = re.compile(r"^AP([0-9a-f]{4})\.([0-9a-f]{4})\.([0-9a-f]{4})$", re.IGNORECASE)


def _mac_from_ap_name(name: str | None) -> str | None:
    if not name:
        return None
    m = _AP_NAME_MAC_RE.match(name.strip())
    if not m:
        return None
    hex_str = "".join(m.groups()).lower()
    return ":".join(hex_str[i : i + 2] for i in range(0, 12, 2))


def _parse_cdp_access_points(cdp_output: str, vlan: int) -> list[APInfo]:
    """Extract only access points from CDP neighbors detail output."""
    aps: list[APInfo] = []
    entries = re.split(r"-{5,}", cdp_output)

    for entry in entries:
        platform_m = re.search(r"Platform:\s*(.+?)(?:,|$)", entry, re.MULTILINE)
        cap_m = re.search(r"Capabilities:\s*(.+)", entry, re.MULTILINE)

        is_ap = False
        platform = ""
        if platform_m:
            platform = platform_m.group(1).strip()
            if _AP_PLATFORM_PATTERNS.search(platform):
                is_ap = True
        if cap_m:
            caps = cap_m.group(1).strip()
            if "Trans-Bridge" in caps:
                is_ap = True

        if not is_ap:
            continue

        local_port_m = re.search(r"Interface:\s*(\S+),", entry)
        name_m = re.search(r"Device ID:\s*(.+)", entry)
        ip_m = re.search(r"IP address:\s*(\d+\.\d+\.\d+\.\d+)", entry)

        local_port = local_port_m.group(1).strip() if local_port_m else ""
        cdp_name = name_m.group(1).strip() if name_m else None
        ap_ip = ip_m.group(1) if ip_m else None

        aps.append(
            APInfo(
                mac_address=_mac_from_ap_name(cdp_name) or "",
                port=local_port,
                vlan=vlan,
                ip_address=ap_ip,
                cdp_name=cdp_name,
                cdp_platform=platform,
            )
        )

    return aps


def _enrich_mac_from_table(aps: list[APInfo], mac_output: str) -> None:
    """Fill in MAC addresses for APs from the MAC address table.

    Only fills gaps left by _mac_from_ap_name (custom-named APs, whose CDP
    device ID doesn't encode a MAC) rather than overwriting it - the CAM
    table entry for a port can be momentarily stale/aged-out even when CDP's
    own (much longer-lived) entry is solid, so a CDP-derived MAC is the more
    reliable of the two when both are available.
    """
    port_to_mac: dict[str, str] = {}
    for line in mac_output.split("\n"):
        m = re.match(
            r"\s*\d+\s+"
            r"([0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4})\s+"
            r"\S+\s+"
            r"(\S+)",
            line,
        )
        if m:
            mac = _format_mac(m.group(1).lower())
            port_key = _normalize_port(m.group(2))
            port_to_mac[port_key] = mac

    for ap in aps:
        if ap.mac_address:
            continue
        port_key = _normalize_port(ap.port)
        if port_key in port_to_mac:
            ap.mac_address = port_to_mac[port_key]


def _format_mac(cisco_mac: str) -> str:
    """Convert Cisco MAC format (0011.2233.4455) to standard (00:11:22:33:44:55)."""
    raw = cisco_mac.replace(".", "").lower()
    if len(raw) == 12:
        return ":".join(raw[i : i + 2] for i in range(0, 12, 2))
    return cisco_mac


def _enrich_poe(aps: list[APInfo], poe_output: str) -> None:
    """Enrich AP list with PoE info."""
    poe_by_port: dict[str, dict] = {}
    for line in poe_output.split("\n"):
        m = re.match(r"\s*(\S+)\s+\S+\s+(\S+)\s+([\d.]+)\s+", line)
        if m:
            port_key = _normalize_port(m.group(1))
            poe_by_port[port_key] = {
                "status": m.group(2),
                "power": m.group(3) + "W",
            }

    for ap in aps:
        port_key = _normalize_port(ap.port)
        if port_key in poe_by_port:
            ap.poe_status = poe_by_port[port_key].get("status")
            ap.poe_power = poe_by_port[port_key].get("power")


def _enrich_arp(aps: list[APInfo], arp_output: str) -> None:
    """Enrich AP list with IP from ARP table."""
    mac_to_ip: dict[str, str] = {}
    for line in arp_output.split("\n"):
        m = re.search(
            r"(\d+\.\d+\.\d+\.\d+)\s+\S+\s+"
            r"([0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4})",
            line,
        )
        if m:
            formatted = _format_mac(m.group(2).lower())
            mac_to_ip[formatted] = m.group(1)

    for ap in aps:
        if ap.mac_address in mac_to_ip:
            ap.ip_address = mac_to_ip[ap.mac_address]


def _normalize_port(port: str) -> str:
    """Normalize port names for comparison (Gi0/1 == GigabitEthernet0/1)."""
    port = port.strip()
    replacements = [
        (r"^GigabitEthernet", "Gi"),
        (r"^FastEthernet", "Fa"),
        (r"^TenGigabitEthernet", "Te"),
        (r"^TwentyFiveGigE", "Twe"),
    ]
    for pattern, repl in replacements:
        port = re.sub(pattern, repl, port)
    return port


def parse_show_version(output: str) -> dict[str, str | None]:
    """hostname, uptime, ios_version and model_info from 'show version'.

    Several fallbacks per field: the wording differs between IOS trains and
    between Catalyst families, and a field that cannot be read stays None
    rather than failing the whole poll.
    """
    fields: dict[str, str | None] = {"hostname": None, "uptime": None, "ios_version": None, "model_info": None}

    m = re.search(r"^(\S+)\s+uptime", output, re.MULTILINE)
    if m:
        fields["hostname"] = m.group(1)

    m = re.search(r"uptime is (.+)", output)
    if m:
        fields["uptime"] = m.group(1).strip()

    m = re.search(r"Cisco IOS Software.*?Version\s+(\S+)", output, re.IGNORECASE)
    if not m:
        m = re.search(r"Version\s+(\S+)", output)
    if m:
        fields["ios_version"] = m.group(1).rstrip(",")

    m = re.search(r"[Mm]odel\s+[Nn]umber\s*:\s*(\S+)", output)
    if not m:
        m = re.search(r"cisco\s+(WS-\S+|C\d+\S*)", output, re.IGNORECASE)
    if not m:
        m = re.search(r"^[Cc]isco\s+(\S+)\s+\(", output, re.MULTILINE)
    if m:
        fields["model_info"] = m.group(1)
    return fields


def parse_port_poe_watts(output: str, interface: str) -> float | None:
    """The PoE draw of `interface` from 'show power inline <interface>'."""
    wanted = _normalize_port(interface)
    for line in output.split("\n"):
        m = re.match(r"\s*(\S+)\s+\S+\s+(\S+)\s+([\d.]+)\s+", line)
        if m and _normalize_port(m.group(1)) == wanted:
            return float(m.group(3))
    return None
