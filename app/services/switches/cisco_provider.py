from __future__ import annotations

import re
import time

from app.domains.inventory.models import NetworkSwitch
from app.services.cisco_ssh import CiscoSSH, get_switch_info
from app.services.switches.base import SwitchPollInfo, SwitchPortState
from app.services.switches.snmp_provider import SnmpSwitchProvider


class CiscoSwitchProvider:
    def __init__(self) -> None:
        self.snmp_provider = SnmpSwitchProvider()

    def poll_switch(self, switch: NetworkSwitch) -> SwitchPollInfo:
        info = get_switch_info(
            switch.ip_address,
            switch.ssh_username,
            switch.ssh_password,
            switch.enable_password,
            switch.ssh_port,
        )
        if info.is_online:
            return SwitchPollInfo(
                is_online=True,
                hostname=info.hostname,
                model_info=info.model_info,
                ios_version=info.ios_version,
                uptime=info.uptime,
            )
        return self.snmp_provider.poll_switch(switch)

    def get_ports(self, switch: NetworkSwitch) -> list[SwitchPortState]:
        ports = self.snmp_provider.get_ports(switch)
        status_map, switchport_map = self._get_status_and_switchport_maps(switch)
        if ports:
            self._enrich_ports_with_status(ports, status_map)
            self._enrich_ports_with_switchport(ports, switchport_map)
            return ports
        ssh_ports = list(status_map.values()) if status_map else self._get_ports_via_ssh(switch)
        self._enrich_ports_with_switchport(ssh_ports, switchport_map)
        return ssh_ports

    def _get_status_and_switchport_maps(
        self, switch: NetworkSwitch
    ) -> tuple[dict[str, SwitchPortState], dict[str, dict[str, str]]]:
        """Fetch both datasets in one SSH session to avoid extra logins."""
        ssh = CiscoSSH(
            switch.ip_address,
            switch.ssh_username,
            switch.ssh_password,
            switch.enable_password,
            switch.ssh_port,
        )
        if not ssh.connect():
            return {}, {}
        try:
            status_output = ssh.execute("show interfaces status")
            switchport_output = ssh.execute("show interfaces switchport")
        finally:
            ssh.close()
        rows = self._parse_interfaces_status(status_output)
        return {self._normalize_port(r.port): r for r in rows}, self._parse_switchport_output(switchport_output)

    def _get_ports_via_ssh(self, switch: NetworkSwitch) -> list[SwitchPortState]:
        ssh = CiscoSSH(
            switch.ip_address,
            switch.ssh_username,
            switch.ssh_password,
            switch.enable_password,
            switch.ssh_port,
        )
        if not ssh.connect():
            return []
        try:
            output = ssh.execute("show interfaces status")
        finally:
            ssh.close()
        return self._parse_interfaces_status(output)

    def _get_interfaces_status_map(self, switch: NetworkSwitch) -> dict[str, SwitchPortState]:
        ssh = CiscoSSH(
            switch.ip_address,
            switch.ssh_username,
            switch.ssh_password,
            switch.enable_password,
            switch.ssh_port,
        )
        if not ssh.connect():
            return {}
        try:
            output = ssh.execute("show interfaces status")
        finally:
            ssh.close()
        rows = self._parse_interfaces_status(output)
        return {self._normalize_port(r.port): r for r in rows}

    def _parse_interfaces_status(self, output: str) -> list[SwitchPortState]:
        ports: list[SwitchPortState] = []
        for line in output.splitlines():
            line = line.rstrip()
            if not line or line.lower().startswith("port ") or line.startswith("---"):
                continue
            parts = line.split()
            if len(parts) < 7:
                continue
            port_name = parts[0]
            media_type = parts[-1]
            speed_text = parts[-2]
            duplex_text = parts[-3]
            vlan_text = parts[-4]
            status_text = parts[-5]
            name_text = " ".join(parts[1:-5]).strip()
            oper_state = "up" if status_text == "connected" else "down"
            port_mode = "trunk" if vlan_text.lower() == "trunk" else ("access" if vlan_text.isdigit() else None)
            vlan_num: int | None = int(vlan_text) if vlan_text.isdigit() else None
            ports.append(
                SwitchPortState(
                    port=port_name,
                    if_index=0,
                    description=name_text if name_text and name_text != "--" else None,
                    admin_status=None,
                    oper_status=oper_state,
                    status_text=status_text,
                    vlan_text=vlan_text,
                    duplex_text=duplex_text,
                    speed_text=speed_text,
                    media_type=media_type,
                    port_mode=port_mode,
                    vlan=vlan_num,
                    access_vlan=vlan_num if port_mode == "access" else None,
                )
            )
        return ports

    def _get_switchport_details(self, switch: NetworkSwitch) -> dict[str, dict[str, str]]:
        ssh = CiscoSSH(
            switch.ip_address,
            switch.ssh_username,
            switch.ssh_password,
            switch.enable_password,
            switch.ssh_port,
        )
        if not ssh.connect():
            return {}
        try:
            output = ssh.execute("show interfaces switchport")
        finally:
            ssh.close()
        return self._parse_switchport_output(output)

    def _parse_switchport_output(self, output: str) -> dict[str, dict[str, str]]:
        sections = re.split(r"\n(?=Name:\s)", output)
        details: dict[str, dict[str, str]] = {}
        for section in sections:
            name_match = re.search(r"Name:\s*(\S+)", section)
            if not name_match:
                continue
            port = name_match.group(1).strip()
            norm = self._normalize_port(port)
            mode_match = re.search(r"Administrative Mode:\s*(.+)", section)
            access_match = re.search(r"Access Mode VLAN:\s*(\d+)", section)
            native_match = re.search(r"Trunking Native Mode VLAN:\s*(\d+)", section)
            allowed_match = re.search(r"Trunking VLANs Enabled:\s*(.+)", section)
            details[norm] = {
                "mode": (mode_match.group(1).strip().lower() if mode_match else ""),
                "access_vlan": access_match.group(1) if access_match else "",
                "native_vlan": native_match.group(1) if native_match else "",
                "allowed_vlans": (allowed_match.group(1).strip() if allowed_match else ""),
            }
        return details

    def _enrich_ports_with_switchport(self, ports: list[SwitchPortState], details: dict[str, dict[str, str]]) -> None:
        for port in ports:
            norm = self._normalize_port(port.port)
            cfg = details.get(norm)
            if not cfg:
                continue
            mode_raw = cfg.get("mode", "")
            port.port_mode = self._normalize_mode(mode_raw)
            if cfg.get("access_vlan"):
                try:
                    port.access_vlan = int(cfg["access_vlan"])
                except ValueError:
                    port.access_vlan = None
            if cfg.get("native_vlan"):
                try:
                    port.trunk_native_vlan = int(cfg["native_vlan"])
                except ValueError:
                    port.trunk_native_vlan = None
            if cfg.get("allowed_vlans"):
                port.trunk_allowed_vlans = cfg["allowed_vlans"]
            # Fill VLAN text/value even when SNMP PVID is missing for this port.
            if port.port_mode == "trunk":
                if not port.vlan_text:
                    port.vlan_text = "trunk"
                if port.vlan is None and port.trunk_native_vlan is not None:
                    port.vlan = port.trunk_native_vlan
            elif port.port_mode == "access":
                if port.vlan is None and port.access_vlan is not None:
                    port.vlan = port.access_vlan
                if not port.vlan_text and port.vlan is not None:
                    port.vlan_text = str(port.vlan)

    def _enrich_ports_with_status(self, ports: list[SwitchPortState], status_map: dict[str, SwitchPortState]) -> None:
        for port in ports:
            status_row = status_map.get(self._normalize_port(port.port))
            if not status_row:
                continue
            if not port.description:
                port.description = status_row.description
            port.oper_status = status_row.oper_status or port.oper_status
            port.status_text = status_row.status_text
            port.vlan_text = status_row.vlan_text
            port.duplex_text = status_row.duplex_text
            port.speed_text = status_row.speed_text
            port.media_type = status_row.media_type
            if status_row.vlan is not None:
                port.vlan = status_row.vlan
            if status_row.port_mode and not port.port_mode:
                port.port_mode = status_row.port_mode
            if status_row.access_vlan is not None and port.access_vlan is None:
                port.access_vlan = status_row.access_vlan

    def _normalize_mode(self, mode_raw: str) -> str | None:
        if not mode_raw:
            return None
        if "trunk" in mode_raw:
            return "trunk"
        if "access" in mode_raw or "static access" in mode_raw:
            return "access"
        if "dynamic" in mode_raw:
            return "dynamic"
        return "unknown"

    def _normalize_port(self, port: str) -> str:
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

    def set_admin_state(self, switch: NetworkSwitch, port: str, admin_state: str) -> None:
        cmd = "no shutdown" if admin_state == "up" else "shutdown"
        self._exec_config(switch, [f"interface {port}", cmd])

    def set_description(self, switch: NetworkSwitch, port: str, description: str) -> None:
        self._exec_config(switch, [f"interface {port}", f"description {description}"])

    def set_vlan(self, switch: NetworkSwitch, port: str, vlan: int) -> None:
        self._exec_config(
            switch,
            [f"interface {port}", "switchport mode access", f"switchport access vlan {vlan}"],
        )

    def set_mode(
        self,
        switch: NetworkSwitch,
        port: str,
        mode: str,
        access_vlan: int | None = None,
        native_vlan: int | None = None,
        allowed_vlans: str | None = None,
    ) -> None:
        normalized = mode.strip().lower()
        if normalized == "access":
            commands = [f"interface {port}", "switchport mode access"]
            if access_vlan is not None:
                commands.append(f"switchport access vlan {access_vlan}")
            self._exec_config(switch, commands)
            return
        if normalized == "trunk":
            commands = [f"interface {port}", "switchport mode trunk"]
            if native_vlan is not None:
                commands.append(f"switchport trunk native vlan {native_vlan}")
            if allowed_vlans:
                commands.append(f"switchport trunk allowed vlan {allowed_vlans}")
            self._exec_config(switch, commands)
            return
        raise RuntimeError("Unsupported mode. Use 'access' or 'trunk'")

    def set_poe(self, switch: NetworkSwitch, port: str, action: str) -> None:
        if action == "on":
            self._exec_config(switch, [f"interface {port}", "power inline auto"])
            return
        if action == "off":
            self._exec_config(switch, [f"interface {port}", "power inline never"])
            return
        ssh = CiscoSSH(
            switch.ip_address,
            switch.ssh_username,
            switch.ssh_password,
            switch.enable_password,
            switch.ssh_port,
        )
        if not ssh.connect():
            raise RuntimeError("SSH connection failed")
        try:
            ssh.execute("configure terminal")
            ssh.execute(f"interface {port}")
            ssh.execute("power inline never")
            ssh.execute("end")
            time.sleep(3)
            ssh.execute("configure terminal")
            ssh.execute(f"interface {port}")
            ssh.execute("power inline auto")
            ssh.execute("end")
        finally:
            ssh.close()

    def _exec_config(self, switch: NetworkSwitch, commands: list[str]) -> None:
        ssh = CiscoSSH(
            switch.ip_address,
            switch.ssh_username,
            switch.ssh_password,
            switch.enable_password,
            switch.ssh_port,
        )
        if not ssh.connect():
            raise RuntimeError("SSH connection failed")
        try:
            ssh.execute("configure terminal")
            for cmd in commands:
                ssh.execute(cmd)
            ssh.execute("end")
        finally:
            ssh.close()
