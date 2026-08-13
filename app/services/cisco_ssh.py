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

from app.observability.metrics import (
    observe_duration,
    ssh_connect_duration_seconds,
    ssh_operations_total,
    ssh_session_reuse_total,
    switch_ops_total,
)

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
    # Set only when is_online is False. See _classify_ssh_error - this is what
    # lets a caller (and the UI) tell "wrong password" apart from "switch
    # unreachable", which the log used to collapse into the same generic
    # "auth failed" regardless of which one actually happened.
    offline_reason: str | None = None


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


def _classify_ssh_error(exc: Exception) -> str:
    """Classify a connect failure so callers can tell "wrong password" apart
    from "switch unreachable" - both surface as a bare Exception from
    paramiko/socket, and every path here used to collapse them into the same
    "auth failed" log line. That mislabeling cost three days of misdiagnosis
    once: a Docker network misconfiguration blackholed all switch traffic,
    but the log said the password was wrong on every single switch.

    Order matters: AuthenticationException must be checked before the
    broader SSHException it subclasses, and OSError before Exception.
    """
    if isinstance(exc, paramiko.AuthenticationException):
        return "auth_rejected"
    if isinstance(exc, socket.gaierror):
        return "dns_failure"
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "timeout"
    if isinstance(exc, ConnectionRefusedError):
        return "connection_refused"
    if isinstance(exc, OSError):
        # Covers "No route to host", "Network is unreachable", and similar -
        # failures that never reach the SSH protocol at all.
        return "network_unreachable"
    if isinstance(exc, paramiko.SSHException):
        return "protocol_error"
    return "other"


# Which auth method actually worked, per (ip, port, username). A switch answers
# the auth-method probe identically every time, so probing on every connect was
# a whole extra TCP+SSH handshake spent learning something already known.
# Entries are dropped the moment the remembered method stops working, so a
# credential or config change re-probes on the next attempt.
_AUTH_METHOD_CACHE: dict[tuple[str, int, str], str] = {}


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
        # Classification of the most recent connect failure (see
        # _classify_ssh_error). None until a connect attempt has failed.
        self.last_failure_reason: str | None = None

    @property
    def _auth_cache_key(self) -> tuple[str, int, str]:
        return (self.ip, self.port, self.username)

    def _strategy_for(self, name: str) -> Callable[[], bool] | None:
        return {
            "password": self._connect_password,
            "keyboard-interactive": self._connect_keyboard_interactive,
        }.get(name)

    def is_alive(self) -> bool:
        if not self.shell or not self.client:
            return False
        transport = self.client.get_transport()
        return bool(transport and transport.is_active())

    def ensure_connected(self) -> bool:
        """Reopen a shared session that has gone away.

        Cisco drops idle VTY sessions on its own exec-timeout (10 minutes by
        default), and one switch cycle can outlive that: rebooting several APs
        means a 45s pause plus up to 240s of verification for each of them.
        """
        if self.is_alive():
            return True
        self.close()
        return self.connect()

    def connect(self) -> bool:
        # Duration of the whole method, cache hit or not: even the cached-
        # method path still pays for a real TCP+auth handshake, it just skips
        # the extra probe connection that used to precede it.
        with observe_duration(ssh_connect_duration_seconds):
            remembered = _AUTH_METHOD_CACHE.get(self._auth_cache_key)
            if remembered:
                method = self._strategy_for(remembered)
                if method and method():
                    ssh_operations_total.labels(operation="connect", result="success", reason=remembered).inc()
                    return True
                # Credentials or the switch's auth config changed - OR the
                # switch simply isn't reachable right now. Either way, forget
                # what we knew and fall through to a full probe; that probe
                # will fail the same way and give us a real classification
                # below instead of assuming it was a credential problem.
                logger.info(
                    "SSH to %s: cached %s auth no longer works (%s), re-probing",
                    self.ip,
                    remembered,
                    self.last_failure_reason,
                )
                _AUTH_METHOD_CACHE.pop(self._auth_cache_key, None)

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
                    _AUTH_METHOD_CACHE[self._auth_cache_key] = name
                    ssh_operations_total.labels(operation="connect", result="success", reason=name).inc()
                    return True
                reason = self.last_failure_reason or "other"
                logger.warning("SSH to %s: %s auth failed (%s)", self.ip, name, reason)
                # reason, not the auth method name: on a genuine auth
                # rejection the two strategies fail for different reasons
                # and both are worth seeing, but on a network-level failure
                # (the common case that used to be mislabeled) both strategies
                # fail identically, and the metric should say so rather than
                # implying two separate credential problems were tried.
                ssh_operations_total.labels(operation="connect", result="error", reason=reason).inc()
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
            self.last_failure_reason = _classify_ssh_error(e)
            logger.debug("SSH password connect to %s: %s (%s)", self.ip, e, self.last_failure_reason)
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
            self.last_failure_reason = _classify_ssh_error(e)
            logger.debug("SSH keyboard-interactive to %s: %s (%s)", self.ip, e, self.last_failure_reason)
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


def _session_for(
    session: CiscoSSH | None,
    ip: str,
    username: str,
    password: str,
    enable_password: str,
    port: int,
) -> tuple[CiscoSSH | None, bool]:
    """Resolve the session an operation should run on.

    Returns (session, owned). `owned` is True when this call opened the
    connection and is therefore responsible for closing it; a session handed
    in by the caller is left open so the next operation in the same cycle can
    reuse it instead of paying for another handshake. Returns (None, ...) if
    no usable connection could be established.

    Every call classifies itself into ssh_session_reuse_total - this is the
    metric that shows the reuse win actually holding cycle over cycle, rather
    than being something only visible by re-reading raw connection logs.
    """
    if session is not None:
        was_alive = session.is_alive()
        if not session.ensure_connected():
            ssh_session_reuse_total.labels(outcome="connect_failed").inc()
            return None, False
        ssh_session_reuse_total.labels(outcome="reused" if was_alive else "new_connection").inc()
        return session, False

    ssh = CiscoSSH(ip, username, password, enable_password, port)
    if ssh.connect():
        ssh_session_reuse_total.labels(outcome="new_connection").inc()
        return ssh, True
    ssh_session_reuse_total.labels(outcome="connect_failed").inc()
    return None, True


def get_switch_info(ip: str, username: str, password: str, enable_password: str = "", port: int = 22) -> SwitchInfo:
    info = SwitchInfo()
    ssh = CiscoSSH(ip, username, password, enable_password, port)
    if not ssh.connect():
        info.offline_reason = ssh.last_failure_reason or "other"
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
    ip: str,
    username: str,
    password: str,
    enable_password: str = "",
    port: int = 22,
    vlan: int = 20,
    session: CiscoSSH | None = None,
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
    ssh, owns_session = _session_for(session, ip, username, password, enable_password, port)
    if ssh is None:
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
        if owns_session:
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

    shut_down = False
    try:
        ssh.execute("configure terminal")
        ssh.execute(f"interface {interface}")
        ssh.execute("shutdown")
        shut_down = True
        time.sleep(3)
        ssh.execute("no shutdown")
        ssh.execute("end")
        logger.info("PoE cycle completed on %s port %s", ip, interface)
        switch_ops_total.labels(operation="reboot_ap_shutdown", result="success").inc()
        return True
    except Exception as e:
        logger.warning("Failed to reboot AP on %s port %s: %s", ip, interface, e)
        if shut_down:
            _try_restore_admin_up(ssh, ip, interface)
        switch_ops_total.labels(operation="reboot_ap_shutdown", result="error").inc()
        return False
    finally:
        ssh.close()


def _try_restore_admin_up(ssh: CiscoSSH, ip: str, interface: str) -> None:
    """Best-effort recovery: a reboot that failed partway MUST NOT leave a
    port administratively shut down forever - that silently kills the AP
    instead of rebooting it. Only reachable after 'shutdown' already ran, so
    this always attempts to undo it, even though the step that failed was
    something else entirely.
    """
    try:
        ssh.execute("configure terminal")
        ssh.execute(f"interface {interface}")
        ssh.execute("no shutdown")
        ssh.execute("end")
        logger.info("Recovered admin-up state on %s port %s after error", ip, interface)
    except Exception as recovery_exc:
        logger.error(
            "CRITICAL: %s port %s may be stuck administratively shut down - recovery attempt also failed: %s",
            ip,
            interface,
            recovery_exc,
        )


def poe_cycle_ap(
    ip: str,
    username: str,
    password: str,
    enable_password: str,
    port: int,
    interface: str,
    session: CiscoSSH | None = None,
) -> bool:
    """Reboot AP via PoE power cycle (cleaner than shutdown)."""
    ssh, owns_session = _session_for(session, ip, username, password, enable_password, port)
    if ssh is None:
        switch_ops_total.labels(operation="reboot_ap_poe", result="error").inc()
        return False

    powered_off = False
    try:
        ssh.execute("configure terminal")
        ssh.execute(f"interface {interface}")
        ssh.execute("power inline never")
        ssh.execute("end")
        powered_off = True
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
        if powered_off:
            _try_restore_poe_auto(ssh, ip, interface)
        switch_ops_total.labels(operation="reboot_ap_poe", result="error").inc()
        return False
    finally:
        if owns_session:
            ssh.close()


def _try_restore_poe_auto(ssh: CiscoSSH, ip: str, interface: str) -> None:
    """Best-effort recovery: a PoE cycle that failed partway MUST NOT leave a
    port permanently unpowered - that's an outage indistinguishable from a
    dead AP, not a reboot. Only reachable after 'power inline never' already
    ran, so this always attempts to restore power, even though the step that
    failed was something else entirely.
    """
    try:
        ssh.execute("configure terminal")
        ssh.execute(f"interface {interface}")
        ssh.execute("power inline auto")
        ssh.execute("end")
        logger.info("Recovered PoE power state on %s port %s after error", ip, interface)
    except Exception as recovery_exc:
        logger.error(
            "CRITICAL: %s port %s may be stuck powered off - recovery attempt also failed: %s",
            ip,
            interface,
            recovery_exc,
        )


def poe_cycle_ports_bulk(
    ip: str, username: str, password: str, enable_password: str, port: int, interfaces: list[str]
) -> bool:
    """PoE-cycle every given port in a single SSH session.

    Used for "reboot all cameras on this switch": looping poe_cycle_ap per
    port would open one SSH session per camera (connect + 5s wait each),
    which for a store with a dozen-plus cameras takes minutes and hits the
    switch with N separate config sessions. Powering all ports off, waiting
    once, then powering all back on is both faster and a real single
    power-cycle event rather than N staggered ones.
    """
    if not interfaces:
        return True
    ssh = CiscoSSH(ip, username, password, enable_password, port)
    if not ssh.connect():
        switch_ops_total.labels(operation="reboot_cameras_bulk_poe", result="error").inc()
        return False

    powering_off_started = False
    try:
        ssh.execute("configure terminal")
        powering_off_started = True
        for interface in interfaces:
            ssh.execute(f"interface {interface}")
            ssh.execute("power inline never")
        ssh.execute("end")
        time.sleep(5)
        ssh.execute("configure terminal")
        for interface in interfaces:
            ssh.execute(f"interface {interface}")
            ssh.execute("power inline auto")
        ssh.execute("end")
        logger.info("Bulk PoE cycle completed on %s ports %s", ip, interfaces)
        switch_ops_total.labels(operation="reboot_cameras_bulk_poe", result="success").inc()
        return True
    except Exception as e:
        logger.warning("Bulk PoE cycle failed on %s ports %s: %s", ip, interfaces, e)
        if powering_off_started:
            # We can't tell how far the power-off loop got before failing,
            # so the only safe recovery is to attempt "power on" for every
            # port in the batch, not just the ones we're sure were touched.
            _try_restore_poe_auto_bulk(ssh, ip, interfaces)
        switch_ops_total.labels(operation="reboot_cameras_bulk_poe", result="error").inc()
        return False
    finally:
        ssh.close()


def _try_restore_poe_auto_bulk(ssh: CiscoSSH, ip: str, interfaces: list[str]) -> None:
    """Best-effort recovery for poe_cycle_ports_bulk - see _try_restore_poe_auto.
    A partial failure here can affect several cameras at once, so this is
    logged at CRITICAL if it doesn't succeed."""
    try:
        ssh.execute("configure terminal")
        for interface in interfaces:
            ssh.execute(f"interface {interface}")
            ssh.execute("power inline auto")
        ssh.execute("end")
        logger.info("Recovered PoE power state on %s ports %s after error", ip, interfaces)
    except Exception as recovery_exc:
        logger.error(
            "CRITICAL: %s ports %s may be stuck powered off - recovery attempt also failed: %s",
            ip,
            interfaces,
            recovery_exc,
        )


def get_port_poe_power(
    ip: str,
    username: str,
    password: str,
    enable_password: str,
    port: int,
    interface: str,
    session: CiscoSSH | None = None,
) -> float | None:
    """Return the PoE draw (watts) on a single port, or None if it's not
    currently powering anything (or the switch couldn't be reached).

    Used before auto-rebooting a *hung* AP (one known from a past scan but
    absent from the current CDP scan) to confirm something is actually
    plugged in and powered before cycling the port - a port with nothing
    drawing power isn't a hung AP, it's an empty port.
    """
    ssh, owns_session = _session_for(session, ip, username, password, enable_password, port)
    if ssh is None:
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
        if owns_session:
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
