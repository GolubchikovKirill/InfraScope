from __future__ import annotations

from app.domains.inventory.models import NetworkSwitch
from app.services.switches.base import SwitchPollInfo, SwitchPortState
from app.services.switches.snmp_provider import SnmpSwitchProvider


class DLinkSwitchProvider:
    """SNMP-first provider for D-Link switches."""

    def __init__(self) -> None:
        self.snmp_provider = SnmpSwitchProvider()

    def poll_switch(self, switch: NetworkSwitch) -> SwitchPollInfo:
        return self.snmp_provider.poll_switch(switch)

    def get_ports(self, switch: NetworkSwitch) -> list[SwitchPortState]:
        return self.snmp_provider.get_ports(switch)

    def set_admin_state(self, switch: NetworkSwitch, port: str, admin_state: str) -> None:
        self.snmp_provider.set_admin_state(switch, port, admin_state)

    def set_description(self, switch: NetworkSwitch, port: str, description: str) -> None:
        self.snmp_provider.set_description(switch, port, description)

    def set_vlan(self, switch: NetworkSwitch, port: str, vlan: int) -> None:
        self.snmp_provider.set_vlan(switch, port, vlan)

    def set_mode(
        self,
        switch: NetworkSwitch,
        port: str,
        mode: str,
        access_vlan: int | None = None,
        native_vlan: int | None = None,
        allowed_vlans: str | None = None,
    ) -> None:
        self.snmp_provider.set_mode(switch, port, mode, access_vlan, native_vlan, allowed_vlans)

    def set_poe(self, switch: NetworkSwitch, port: str, action: str) -> None:
        self.snmp_provider.set_poe(switch, port, action)
