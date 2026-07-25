"""SSH client for Cisco IOS switches.

Supports:
  - Fetching switch info (hostname, model, IOS version, uptime)
  - Discovering access points on a VLAN via MAC address table + CDP + PoE
  - Rebooting access points via PoE power cycling
"""

from __future__ import annotations

import logging
import re
import socket
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass

import paramiko

from app.observability.metrics import ssh_operations_total, switch_ops_total

logger = logging.getLogger(__name__)

SSH_TIMEOUT = 15
CMD_TIMEOUT = 30
RECV_CHUNK = 65535
RECV_WAIT = 0.5


@dataclass
class SwitchInfo:
    hostname: str | None = None
    model_info: str | None = None
    ios_version: str | None = None
    uptime: str | None = None
    is_online: bool = False


@dataclass
class APInfo:
    mac_address: str
    port: str
    vlan: int
    ip_address: str | None = None
    cdp_name: str | None = None
    cdp_platform: str | None = None
    poe_power: str | None = None
    poe_status: str | None = None


@dataclass
class CameraPortInfo:
    """A port on a camera VLAN. Cameras don't announce themselves via CDP/LLDP
    the way autonomous APs do, so unlike APInfo this is identified purely by
    VLAN membership plus link/PoE state - it's every port on a camera VLAN
    that's currently up, not a positively-identified camera."""

    port: str
    vlan: int
    oper_status: str
    description: str | None = None
    poe_power: str | None = None
    poe_status: str | None = None


class CiscoSSH:
    """Manages an SSH session to a Cisco IOS device."""

    def __init__(self, ip: str, username: str, password: str, enable_password: str = "", port: int = 22):
        self.ip = ip
        self.username = username
        self.password = password
        self.enable_password = enable_password or password
        self.port = port
        self.client: paramiko.SSHClient | None = None
        self.shell: paramiko.Channel | None = None

    def connect(self) -> bool:
        allowed = self._query_auth_methods()
        logger.info("SSH to %s: server allows auth methods: %s", self.ip, allowed)

        strategies: list[tuple[str, Callable[[], bool]]] = []
        if "password" in allowed:
            strategies.append(("password", self._connect_password))
        if "keyboard-interactive" in allowed:
            strategies.append(("keyboard-interactive", self._connect_keyboard_interactive))
        if not strategies:
            strategies = [
                ("password", self._connect_password),
                ("keyboard-interactive", self._connect_keyboard_interactive),
            ]

        for name, method in strategies:
            logger.info("SSH to %s: trying %s auth", self.ip, name)
            if method():
                logger.info("SSH to %s: %s auth succeeded", self.ip, name)
                ssh_operations_total.labels(operation="connect", result="success", reason=name).inc()
                return True
            logger.warning("SSH to %s: %s auth failed", self.ip, name)
            ssh_operations_total.labels(operation="connect", result="error", reason=name).inc()
        return False

    def _query_auth_methods(self) -> list[str]:
        """Ask the server which auth methods it supports."""
        transport: paramiko.Transport | None = None
        try:
            transport = self._open_transport()
            try:
                transport.auth_none(self.username)
            except paramiko.BadAuthenticationType as e:
                return list(e.allowed_types)
            except paramiko.AuthenticationException:
                return ["password", "keyboard-interactive"]
        except Exception as e:
            logger.debug("SSH auth query to %s failed: %s", self.ip, e)
        finally:
            if transport is not None:
                transport.close()
        return ["password", "keyboard-interactive"]

    def _connect_password(self) -> bool:
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.client.connect(
                self.ip,
                port=self.port,
                username=self.username,
                password=self.password,
                timeout=SSH_TIMEOUT,
                auth_timeout=SSH_TIMEOUT,
                banner_timeout=SSH_TIMEOUT,
                look_for_keys=False,
                allow_agent=False,
                disabled_algorithms={"pubkeys": ["rsa-sha2-512", "rsa-sha2-256"]},
            )
            return self._post_connect()
        except Exception as e:
            logger.debug("SSH password connect to %s: %s", self.ip, e)
            self.close()
            return False

    def _connect_keyboard_interactive(self) -> bool:
        """Cisco often uses keyboard-interactive instead of standard password auth."""
        transport: paramiko.Transport | None = None
        try:
            transport = self._open_transport()
            transport.set_keepalive(30)

            password = self.password

            def _ki_handler(_title, _instructions, prompt_list):
                logger.debug("KI prompts from %s: %s", self.ip, prompt_list)
                return [password] * len(prompt_list)

            transport.auth_interactive(self.username, _ki_handler)

            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.client._transport = transport
            self.shell = transport.open_session()
            self.shell.get_pty()
            self.shell.invoke_shell()
            self.shell.settimeout(CMD_TIMEOUT)
            self._recv_until_prompt()

            self._enter_enable()
            self._send("terminal length 0")
            self._recv_until_prompt()
            return True
        except Exception as e:
            logger.debug("SSH keyboard-interactive to %s: %s", self.ip, e)
            self.close()
            return False
        finally:
            if transport is not None and self.client is None:
                transport.close()

    def _open_transport(self) -> paramiko.Transport:
        """Open SSH transport with explicit socket timeout safeguards."""
        sock = socket.create_connection((self.ip, self.port), timeout=SSH_TIMEOUT)
        transport = paramiko.Transport(sock)
        transport.banner_timeout = SSH_TIMEOUT
        transport.start_client(timeout=SSH_TIMEOUT)
        return transport

    def _post_connect(self) -> bool:
        """Open shell and enter privileged mode after successful transport auth."""
        self.shell = self.client.invoke_shell()  # type: ignore[union-attr]
        self.shell.settimeout(CMD_TIMEOUT)
        self._recv_until_prompt()
        self._enter_enable()
        self._send("terminal length 0")
        self._recv_until_prompt()
        return True

    def _enter_enable(self) -> None:
        self._send("enable")
        output = self._recv_until_prompt()
        if "assword" in output:
            self._send(self.enable_password)
            self._recv_until_prompt()

    def close(self) -> None:
        try:
            if self.shell:
                # Graceful session teardown on Cisco side before channel close.
                with suppress(Exception):
                    self.shell.send("exit\n")
                with suppress(Exception):
                    self.shell.close()
            if self.client:
                with suppress(Exception):
                    transport = self.client.get_transport()
                    if transport:
                        transport.close()
                with suppress(Exception):
                    self.client.close()
        except Exception:
            pass
        self.shell = None
        self.client = None

    def _send(self, cmd: str) -> None:
        if self.shell:
            self.shell.send(cmd + "\n")

    def _recv_until_prompt(self, timeout: float = CMD_TIMEOUT) -> str:
        if not self.shell:
            return ""
        output = ""
        end_time = time.monotonic() + timeout
        while time.monotonic() < end_time:
            time.sleep(RECV_WAIT)
            if self.shell.recv_ready():
                chunk = self.shell.recv(RECV_CHUNK).decode("utf-8", errors="replace")
                output += chunk
                if re.search(r"[#>]\s*$", output):
                    break
            elif output and re.search(r"[#>]\s*$", output):
                break
        return output

    def execute(self, cmd: str) -> str:
        self._send(cmd)
        return self._recv_until_prompt()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()


def get_switch_info(ip: str, username: str, password: str, enable_password: str = "", port: int = 22) -> SwitchInfo:
    info = SwitchInfo()
    ssh = CiscoSSH(ip, username, password, enable_password, port)
    if not ssh.connect():
        switch_ops_total.labels(operation="poll_info", result="error").inc()
        return info

    try:
        info.is_online = True
        output = ssh.execute("show version")

        m = re.search(r"^(\S+)\s+uptime", output, re.MULTILINE)
        if m:
            info.hostname = m.group(1)

        m = re.search(r"uptime is (.+)", output)
        if m:
            info.uptime = m.group(1).strip()

        m = re.search(r"Cisco IOS Software.*?Version\s+(\S+)", output, re.IGNORECASE)
        if not m:
            m = re.search(r"Version\s+(\S+)", output)
        if m:
            info.ios_version = m.group(1).rstrip(",")

        m = re.search(r"[Mm]odel\s+[Nn]umber\s*:\s*(\S+)", output)
        if not m:
            m = re.search(r"cisco\s+(WS-\S+|C\d+\S*)", output, re.IGNORECASE)
        if not m:
            m = re.search(r"^[Cc]isco\s+(\S+)\s+\(", output, re.MULTILINE)
        if m:
            info.model_info = m.group(1)
    except Exception as e:
        logger.warning("Failed to get switch info from %s: %s", ip, e)
        switch_ops_total.labels(operation="poll_info", result="error").inc()
    finally:
        ssh.close()

    switch_ops_total.labels(operation="poll_info", result="success").inc()
    return info


def get_access_points(
    ip: str, username: str, password: str, enable_password: str = "", port: int = 22, vlan: int = 20
) -> list[APInfo] | None:
    """Discover access points on the given VLAN using CDP as primary source.

    Returns None if the switch could not be scanned at all (SSH connection
    or the CDP command itself failed), distinct from an empty list, which
    means the scan succeeded and genuinely found zero APs. Callers must not
    treat None the same as []: doing so would let a transient SSH hiccup
    (e.g. the switch's VTY session limit) look identical to "every known AP
    on this switch just went silent", which is exactly what the auto-reboot
    hung-AP detection watches for.
    """
    ssh = CiscoSSH(ip, username, password, enable_password, port)
    if not ssh.connect():
        switch_ops_total.labels(operation="access_points", result="error").inc()
        return None

    try:
        try:
            cdp_output = ssh.execute("show cdp neighbors detail")
        except Exception as e:
            logger.warning("Failed to get CDP neighbors from %s: %s", ip, e)
            switch_ops_total.labels(operation="access_points", result="error").inc()
            return None

        aps = _parse_cdp_access_points(cdp_output, vlan)
        logger.info("CDP found %d access points on %s vlan %d", len(aps), ip, vlan)

        if not aps:
            switch_ops_total.labels(operation="access_points", result="success").inc()
            return []

        # Enrichment failures shouldn't discard APs CDP already found - each
        # step is independent and best-effort.
        try:
            mac_output = ssh.execute(f"show mac address-table vlan {vlan}")
            _enrich_mac_from_table(aps, mac_output)
        except Exception as e:
            logger.warning("MAC table enrichment failed for %s: %s", ip, e)

        try:
            poe_output = ssh.execute("show power inline")
            _enrich_poe(aps, poe_output)
        except Exception as e:
            logger.warning("PoE enrichment failed for %s: %s", ip, e)

        try:
            arp_output = ssh.execute(f"show ip arp vlan {vlan}")
            _enrich_arp(aps, arp_output)
        except Exception as e:
            logger.warning("ARP enrichment failed for %s: %s", ip, e)

        switch_ops_total.labels(operation="access_points", result="success").inc()
        return aps
    except Exception as e:
        logger.warning("Failed to get APs from %s: %s", ip, e)
        switch_ops_total.labels(operation="access_points", result="error").inc()
        return None
    finally:
        ssh.close()


def get_camera_ports(
    ip: str, username: str, password: str, enable_password: str, port: int, camera_vlans: set[int]
) -> list[CameraPortInfo] | None:
    """Ports whose access VLAN is one of camera_vlans, for manual identification
    and PoE-cycling of a dropped camera. Returns None if the switch could not
    be scanned at all (SSH failure), distinct from an empty list, for the same
    reason get_access_points does: a failed scan must not look like "no camera
    ports exist" to a caller.
    """
    ssh = CiscoSSH(ip, username, password, enable_password, port)
    if not ssh.connect():
        switch_ops_total.labels(operation="camera_ports", result="error").inc()
        return None

    try:
        try:
            status_output = ssh.execute("show interfaces status")
        except Exception as e:
            logger.warning("Failed to get interface status from %s: %s", ip, e)
            switch_ops_total.labels(operation="camera_ports", result="error").inc()
            return None

        ports = _parse_ports_on_vlans(status_output, camera_vlans)

        try:
            poe_output = ssh.execute("show power inline")
            _enrich_camera_poe(ports, poe_output)
        except Exception as e:
            logger.warning("PoE enrichment failed for %s: %s", ip, e)

        switch_ops_total.labels(operation="camera_ports", result="success").inc()
        return ports
    except Exception as e:
        logger.warning("Failed to get camera ports from %s: %s", ip, e)
        switch_ops_total.labels(operation="camera_ports", result="error").inc()
        return None
    finally:
        ssh.close()


@dataclass
class InterfaceStatusRow:
    """One row of 'show interfaces status', before any caller-specific shaping."""

    port: str
    status: str  # connected | notconnect | disabled | err-disabled | monitor | inactive
    vlan_text: str
    duplex_text: str
    speed_text: str
    media_type: str
    name: str | None = None


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
    for line in output.splitlines():
        line = line.rstrip()
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


def reboot_ap(ip: str, username: str, password: str, enable_password: str, port: int, interface: str) -> bool:
    """Reboot an AP by PoE cycling the switch port."""
    ssh = CiscoSSH(ip, username, password, enable_password, port)
    if not ssh.connect():
        switch_ops_total.labels(operation="reboot_ap_shutdown", result="error").inc()
        return False

    try:
        ssh.execute("configure terminal")
        ssh.execute(f"interface {interface}")
        ssh.execute("shutdown")
        time.sleep(3)
        ssh.execute("no shutdown")
        ssh.execute("end")
        logger.info("PoE cycle completed on %s port %s", ip, interface)
        switch_ops_total.labels(operation="reboot_ap_shutdown", result="success").inc()
        return True
    except Exception as e:
        logger.warning("Failed to reboot AP on %s port %s: %s", ip, interface, e)
        switch_ops_total.labels(operation="reboot_ap_shutdown", result="error").inc()
        return False
    finally:
        ssh.close()


def poe_cycle_ap(ip: str, username: str, password: str, enable_password: str, port: int, interface: str) -> bool:
    """Reboot AP via PoE power cycle (cleaner than shutdown)."""
    ssh = CiscoSSH(ip, username, password, enable_password, port)
    if not ssh.connect():
        switch_ops_total.labels(operation="reboot_ap_poe", result="error").inc()
        return False

    try:
        ssh.execute("configure terminal")
        ssh.execute(f"interface {interface}")
        ssh.execute("power inline never")
        ssh.execute("end")
        time.sleep(5)
        ssh.execute("configure terminal")
        ssh.execute(f"interface {interface}")
        ssh.execute("power inline auto")
        ssh.execute("end")
        logger.info("PoE power cycle completed on %s port %s", ip, interface)
        switch_ops_total.labels(operation="reboot_ap_poe", result="success").inc()
        return True
    except Exception as e:
        logger.warning("PoE cycle failed on %s port %s: %s", ip, interface, e)
        switch_ops_total.labels(operation="reboot_ap_poe", result="error").inc()
        return False
    finally:
        ssh.close()


def get_port_poe_power(ip: str, username: str, password: str, enable_password: str, port: int, interface: str) -> float | None:
    """Return the PoE draw (watts) on a single port, or None if it's not
    currently powering anything (or the switch couldn't be reached).

    Used before auto-rebooting a *hung* AP (one known from a past scan but
    absent from the current CDP scan) to confirm something is actually
    plugged in and powered before cycling the port - a port with nothing
    drawing power isn't a hung AP, it's an empty port.
    """
    ssh = CiscoSSH(ip, username, password, enable_password, port)
    if not ssh.connect():
        return None
    try:
        output = ssh.execute(f"show power inline {interface}")
        for line in output.split("\n"):
            m = re.match(r"\s*(\S+)\s+\S+\s+(\S+)\s+([\d.]+)\s+", line)
            if m and _normalize_port(m.group(1)) == _normalize_port(interface):
                return float(m.group(3))
        return None
    except Exception as e:
        logger.warning("PoE status check failed on %s port %s: %s", ip, interface, e)
        return None
    finally:
        ssh.close()


def get_switch_arp_mac_map(ip: str, username: str, password: str, enable_password: str, port: int) -> dict[str, str]:
    """Best-effort mac->ip map read from this switch's own ARP table.

    Read-only, single SSH session. Used as a fast/quiet first source for
    MAC-based device rediscovery (app.services.switch_mac_lookup) ahead of
    the ARP-table + ping-sweep fallback in mac_rediscovery.py - reading a
    table the switch already has costs nothing on the network, unlike a
    ping sweep across a whole subnet.
    """
    ssh = CiscoSSH(ip, username, password, enable_password, port)
    if not ssh.connect():
        return {}
    try:
        arp_output = ssh.execute("show ip arp")
        return _parse_arp_mac_to_ip(arp_output)
    except Exception as e:
        logger.warning("ARP map fetch failed on %s: %s", ip, e)
        return {}
    finally:
        ssh.close()


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
                mac_address="",
                port=local_port,
                vlan=vlan,
                ip_address=ap_ip,
                cdp_name=cdp_name,
                cdp_platform=platform,
            )
        )

    return aps


def _enrich_mac_from_table(aps: list[APInfo], mac_output: str) -> None:
    """Fill in MAC addresses for APs from the MAC address table."""
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
