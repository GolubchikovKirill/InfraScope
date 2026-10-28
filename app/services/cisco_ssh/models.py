"""What the Cisco client hands back: plain records, no behaviour."""

from __future__ import annotations

from dataclasses import dataclass


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
