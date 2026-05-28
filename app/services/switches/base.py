from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.domains.inventory.models import NetworkSwitch


@dataclass
class SwitchPollInfo:
    is_online: bool
    hostname: str | None = None
    model_info: str | None = None
    ios_version: str | None = None
    uptime: str | None = None


@dataclass
class SwitchPortState:
    port: str
    if_index: int
    description: str | None = None
    admin_status: str | None = None
    oper_status: str | None = None
    status_text: str | None = None
    vlan_text: str | None = None
    duplex_text: str | None = None
    speed_text: str | None = None
    media_type: str | None = None
    speed_mbps: int | None = None
    duplex: str | None = None
    vlan: int | None = None
    port_mode: str | None = None  # access | trunk | dynamic | unknown
    access_vlan: int | None = None
    trunk_native_vlan: int | None = None
    trunk_allowed_vlans: str | None = None
    poe_enabled: bool | None = None
    poe_power_w: float | None = None
    mac_count: int | None = None


class SwitchProvider(Protocol):
    def poll_switch(self, switch: NetworkSwitch) -> SwitchPollInfo: ...

    def get_ports(self, switch: NetworkSwitch) -> list[SwitchPortState]: ...

    def set_admin_state(self, switch: NetworkSwitch, port: str, admin_state: str) -> None: ...

    def set_description(self, switch: NetworkSwitch, port: str, description: str) -> None: ...

    def set_vlan(self, switch: NetworkSwitch, port: str, vlan: int) -> None: ...

    def set_mode(
        self,
        switch: NetworkSwitch,
        port: str,
        mode: str,
        access_vlan: int | None = None,
        native_vlan: int | None = None,
        allowed_vlans: str | None = None,
    ) -> None: ...

    def set_poe(self, switch: NetworkSwitch, port: str, action: str) -> None: ...
