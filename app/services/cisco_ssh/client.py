"""Operations against one Cisco IOS switch.

`CiscoSwitchClient` holds a switch's connection parameters once - every
operation used to take the same five arguments (ip, username, password,
enable password, port) - and owns the shape all of them share: open or reuse a
session, run commands, count the outcome, close what it opened. Parsing lives
in `parsers`, the SSH session itself in `session`.

Write operations (shutdown / PoE cycles) follow one rule: once a port has been
taken down, any later failure must still try to bring it back up. A reboot that
dies halfway must not turn into an outage.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

from app.observability.metrics import switch_ops_total

from . import session as _session
from .models import APInfo, CameraPortInfo, SwitchInfo
from .parsers import (
    _enrich_arp,
    _enrich_camera_poe,
    _enrich_mac_from_table,
    _enrich_poe,
    _parse_arp_mac_to_ip,
    _parse_cdp_access_points,
    _parse_ports_on_vlans,
    parse_port_poe_watts,
    parse_show_version,
)

logger = logging.getLogger("app.services.cisco_ssh")

#: How long a port stays down during a reboot. Shutdown is a link flap; PoE
#: needs the AP's capacitors to drain before it really power-cycles.
SHUTDOWN_HOLD_SECONDS = 3
POE_OFF_HOLD_SECONDS = 5


class CiscoSwitchClient:
    def __init__(self, ip: str, username: str, password: str, enable_password: str = "", port: int = 22) -> None:
        self.ip = ip
        self.username = username
        self.password = password
        self.enable_password = enable_password
        self.port = port
        # Why the last fresh connect failed (see session._classify_ssh_error)
        self.last_failure_reason: str | None = None

    # -- sessions ------------------------------------------------------------

    def _new_session(self) -> _session.CiscoSSH:
        # Looked up on the module so tests (and only tests) can swap the class.
        return _session.CiscoSSH(self.ip, self.username, self.password, self.enable_password, self.port)

    def _resolve(self, session: _session.CiscoSSH | None) -> tuple[_session.CiscoSSH | None, bool]:
        return _session._session_for(session, self.ip, self.username, self.password, self.enable_password, self.port)

    @contextmanager
    def _connected(self, session: _session.CiscoSSH | None = None) -> Iterator[_session.CiscoSSH | None]:
        """A live session or None; closes it afterwards only if it opened it.

        A session handed in by the caller stays open for the next operation of
        the same cycle - that reuse is what ssh_session_reuse_total tracks.
        """
        ssh, owned = self._resolve(session)
        try:
            yield ssh
        finally:
            if ssh is not None and owned:
                ssh.close()

    @contextmanager
    def _fresh(self) -> Iterator[_session.CiscoSSH | None]:
        """A new session for one operation, always closed afterwards."""
        ssh = self._new_session()
        if not ssh.connect():
            self.last_failure_reason = getattr(ssh, "last_failure_reason", None)
            yield None
            return
        try:
            yield ssh
        finally:
            ssh.close()

    # -- reads ---------------------------------------------------------------

    def switch_info(self) -> SwitchInfo:
        info = SwitchInfo()
        with self._fresh() as ssh:
            if ssh is None:
                info.offline_reason = self.last_failure_reason or "other"
                switch_ops_total.labels(operation="poll_info", result="error").inc()
                return info
            info.is_online = True
            try:
                for field, value in parse_show_version(ssh.execute("show version")).items():
                    setattr(info, field, value)
            except Exception as e:
                logger.warning("Failed to get switch info from %s: %s", self.ip, e)
                switch_ops_total.labels(operation="poll_info", result="error").inc()
        switch_ops_total.labels(operation="poll_info", result="success").inc()
        return info

    def access_points(self, vlan: int = 20, session: _session.CiscoSSH | None = None) -> list[APInfo] | None:
        """Access points on `vlan`, found by CDP and enriched from MAC/PoE/ARP.

        None means the switch could not be scanned at all (SSH or the CDP
        command failed); [] means it was scanned and has none. Callers must
        keep the two apart: treating a transient SSH hiccup (say, the VTY
        session limit) as "every known AP went silent" is exactly what the
        auto-reboot hung-AP detection would act on.
        """
        with self._connected(session) as ssh:
            if ssh is None:
                switch_ops_total.labels(operation="access_points", result="error").inc()
                return None
            try:
                try:
                    cdp_output = ssh.execute("show cdp neighbors detail")
                except Exception as e:
                    logger.warning("Failed to get CDP neighbors from %s: %s", self.ip, e)
                    switch_ops_total.labels(operation="access_points", result="error").inc()
                    return None

                aps = _parse_cdp_access_points(cdp_output, vlan)
                logger.info("CDP found %d access points on %s vlan %d", len(aps), self.ip, vlan)
                if not aps:
                    switch_ops_total.labels(operation="access_points", result="success").inc()
                    return []

                # Enrichment failures shouldn't discard APs CDP already found -
                # each step is independent and best-effort.
                self._enrich(ssh, f"show mac address-table vlan {vlan}", "MAC table", _enrich_mac_from_table, aps)
                self._enrich(ssh, "show power inline", "PoE", _enrich_poe, aps)
                self._enrich(ssh, f"show ip arp vlan {vlan}", "ARP", _enrich_arp, aps)

                switch_ops_total.labels(operation="access_points", result="success").inc()
                return aps
            except Exception as e:
                logger.warning("Failed to get APs from %s: %s", self.ip, e)
                switch_ops_total.labels(operation="access_points", result="error").inc()
                return None

    def camera_ports(self, camera_vlans: set[int]) -> list[CameraPortInfo] | None:
        """Ports whose access VLAN is a camera VLAN, for finding and PoE-cycling
        a dropped camera. None on a failed scan, for the same reason as
        access_points: a failed scan must not look like "no camera ports"."""
        with self._fresh() as ssh:
            if ssh is None:
                switch_ops_total.labels(operation="camera_ports", result="error").inc()
                return None
            try:
                try:
                    status_output = ssh.execute("show interfaces status")
                except Exception as e:
                    logger.warning("Failed to get interface status from %s: %s", self.ip, e)
                    switch_ops_total.labels(operation="camera_ports", result="error").inc()
                    return None
                ports = _parse_ports_on_vlans(status_output, camera_vlans)
                self._enrich(ssh, "show power inline", "PoE", _enrich_camera_poe, ports)
                switch_ops_total.labels(operation="camera_ports", result="success").inc()
                return ports
            except Exception as e:
                logger.warning("Failed to get camera ports from %s: %s", self.ip, e)
                switch_ops_total.labels(operation="camera_ports", result="error").inc()
                return None

    def port_poe_watts(self, interface: str, session: _session.CiscoSSH | None = None) -> float | None:
        """PoE draw on one port, or None if nothing is powered (or no session).

        Checked before auto-rebooting a *hung* AP - one known from an earlier
        scan but missing from this one: a port drawing no power holds no hung
        AP, it is simply empty.
        """
        with self._connected(session) as ssh:
            if ssh is None:
                return None
            try:
                return parse_port_poe_watts(ssh.execute(f"show power inline {interface}"), interface)
            except Exception as e:
                logger.warning("PoE status check failed on %s port %s: %s", self.ip, interface, e)
                return None

    def arp_mac_map(self) -> dict[str, str]:
        """Best-effort mac -> ip map from the switch's own ARP table.

        Read-only, one session. The cheap first source for MAC-based device
        rediscovery (app.services.switch_mac_lookup), ahead of the ping sweep
        in mac_rediscovery: reading a table the switch already has costs the
        network nothing.
        """
        with self._fresh() as ssh:
            if ssh is None:
                return {}
            try:
                return _parse_arp_mac_to_ip(ssh.execute("show ip arp"))
            except Exception as e:
                logger.warning("ARP map fetch failed on %s: %s", self.ip, e)
                return {}

    def _enrich(self, ssh: _session.CiscoSSH, command: str, what: str, enrich, records: list) -> None:
        try:
            enrich(records, ssh.execute(command))
        except Exception as e:
            logger.warning("%s enrichment failed for %s: %s", what, self.ip, e)

    # -- writes --------------------------------------------------------------

    def reboot_ap(self, interface: str) -> bool:
        """Reboot an AP by shutting its port down and back up."""
        with self._fresh() as ssh:
            if ssh is None:
                switch_ops_total.labels(operation="reboot_ap_shutdown", result="error").inc()
                return False
            shut_down = False
            try:
                self._configure(ssh, [interface], "shutdown")
                shut_down = True
                time.sleep(SHUTDOWN_HOLD_SECONDS)
                ssh.execute("no shutdown")
                ssh.execute("end")
                logger.info("PoE cycle completed on %s port %s", self.ip, interface)
                switch_ops_total.labels(operation="reboot_ap_shutdown", result="success").inc()
                return True
            except Exception as e:
                logger.warning("Failed to reboot AP on %s port %s: %s", self.ip, interface, e)
                if shut_down:
                    self._restore(ssh, [interface], "no shutdown", "admin-up state", "administratively shut down")
                switch_ops_total.labels(operation="reboot_ap_shutdown", result="error").inc()
                return False

    def poe_cycle(self, interface: str, session: _session.CiscoSSH | None = None) -> bool:
        """Reboot an AP by cutting PoE power (cleaner than a shutdown)."""
        with self._connected(session) as ssh:
            if ssh is None:
                switch_ops_total.labels(operation="reboot_ap_poe", result="error").inc()
                return False
            powered_off = False
            try:
                self._configure(ssh, [interface], "power inline never")
                ssh.execute("end")
                powered_off = True
                time.sleep(POE_OFF_HOLD_SECONDS)
                self._configure(ssh, [interface], "power inline auto")
                ssh.execute("end")
                logger.info("PoE power cycle completed on %s port %s", self.ip, interface)
                switch_ops_total.labels(operation="reboot_ap_poe", result="success").inc()
                return True
            except Exception as e:
                logger.warning("PoE cycle failed on %s port %s: %s", self.ip, interface, e)
                if powered_off:
                    self._restore(ssh, [interface], "power inline auto", "PoE power state", "powered off")
                switch_ops_total.labels(operation="reboot_ap_poe", result="error").inc()
                return False

    def poe_cycle_bulk(self, interfaces: list[str]) -> bool:
        """PoE-cycle every given port in one session.

        "Reboot all cameras on this switch": one session per camera meant a
        connect plus a 5 s hold each - minutes for a store with a dozen
        cameras, and N config sessions on the switch. All off, one wait, all
        on is faster and one real power-cycle event instead of N staggered.
        """
        if not interfaces:
            return True
        with self._fresh() as ssh:
            if ssh is None:
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
                time.sleep(POE_OFF_HOLD_SECONDS)
                self._configure(ssh, interfaces, "power inline auto")
                ssh.execute("end")
                logger.info("Bulk PoE cycle completed on %s ports %s", self.ip, interfaces)
                switch_ops_total.labels(operation="reboot_cameras_bulk_poe", result="success").inc()
                return True
            except Exception as e:
                logger.warning("Bulk PoE cycle failed on %s ports %s: %s", self.ip, interfaces, e)
                if powering_off_started:
                    # How far the power-off loop got is unknown, so every port
                    # in the batch gets "power on", not just the known ones.
                    self._restore(ssh, interfaces, "power inline auto", "PoE power state", "powered off")
                switch_ops_total.labels(operation="reboot_cameras_bulk_poe", result="error").inc()
                return False

    @staticmethod
    def _configure(ssh: _session.CiscoSSH, interfaces: list[str], command: str) -> None:
        """configure terminal, then `command` on each interface (no "end")."""
        ssh.execute("configure terminal")
        for interface in interfaces:
            ssh.execute(f"interface {interface}")
            ssh.execute(command)

    def _restore(self, ssh: _session.CiscoSSH, interfaces: list[str], command: str, state: str, stuck: str) -> None:
        """Best-effort undo after a write failed partway. Only reached once the
        port was already taken down, so it always tries, whatever step failed;
        if even this fails the port may stay dead, which is logged CRITICAL."""
        target = interfaces[0] if len(interfaces) == 1 else interfaces
        noun = "port" if len(interfaces) == 1 else "ports"
        try:
            self._configure(ssh, interfaces, command)
            ssh.execute("end")
            logger.info("Recovered %s on %s %s %s after error", state, self.ip, noun, target)
        except Exception as recovery_exc:
            logger.error(
                "CRITICAL: %s %s %s may be stuck %s - recovery attempt also failed: %s",
                self.ip,
                noun,
                target,
                stuck,
                recovery_exc,
            )


# -- function API -------------------------------------------------------------
# The call sites (providers, routes, auto-reboot) predate the class and pass the
# connection parameters on every call; these keep that signature.


def get_switch_info(ip: str, username: str, password: str, enable_password: str = "", port: int = 22) -> SwitchInfo:
    return CiscoSwitchClient(ip, username, password, enable_password, port).switch_info()


def get_access_points(
    ip: str,
    username: str,
    password: str,
    enable_password: str = "",
    port: int = 22,
    vlan: int = 20,
    session: _session.CiscoSSH | None = None,
) -> list[APInfo] | None:
    return CiscoSwitchClient(ip, username, password, enable_password, port).access_points(vlan, session=session)


def get_camera_ports(
    ip: str, username: str, password: str, enable_password: str, port: int, camera_vlans: set[int]
) -> list[CameraPortInfo] | None:
    return CiscoSwitchClient(ip, username, password, enable_password, port).camera_ports(camera_vlans)


def reboot_ap(ip: str, username: str, password: str, enable_password: str, port: int, interface: str) -> bool:
    return CiscoSwitchClient(ip, username, password, enable_password, port).reboot_ap(interface)


def poe_cycle_ap(
    ip: str,
    username: str,
    password: str,
    enable_password: str,
    port: int,
    interface: str,
    session: _session.CiscoSSH | None = None,
) -> bool:
    return CiscoSwitchClient(ip, username, password, enable_password, port).poe_cycle(interface, session=session)


def poe_cycle_ports_bulk(
    ip: str, username: str, password: str, enable_password: str, port: int, interfaces: list[str]
) -> bool:
    return CiscoSwitchClient(ip, username, password, enable_password, port).poe_cycle_bulk(interfaces)


def get_port_poe_power(
    ip: str,
    username: str,
    password: str,
    enable_password: str,
    port: int,
    interface: str,
    session: _session.CiscoSSH | None = None,
) -> float | None:
    return CiscoSwitchClient(ip, username, password, enable_password, port).port_poe_watts(interface, session=session)


def get_switch_arp_mac_map(ip: str, username: str, password: str, enable_password: str, port: int) -> dict[str, str]:
    return CiscoSwitchClient(ip, username, password, enable_password, port).arp_mac_map()
