from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from .common import _normalize_mac, _validate_ip

__all__ = [
    "NetworkSwitchCreate",
    "NetworkSwitchUpdate",
    "NetworkSwitchPublic",
    "NetworkSwitchesPublic",
    "AccessPointInfo",
    "CameraPortInfo",
    "AutoRebootSummary",
    "SetApExcludedRequest",
    "SwitchPortInfo",
    "SwitchPortsPublic",
    "SwitchPortAdminStateUpdate",
    "SwitchPortDescriptionUpdate",
    "SwitchPortVlanUpdate",
    "SwitchPortPoeUpdate",
    "SwitchPortModeUpdate",
    "SwitchPortSnapshotEntry",
    "SwitchPortSnapshotHistory",
]


class NetworkSwitchCreate(BaseModel):
    name: str
    ip_address: str
    ssh_username: str = "admin"
    ssh_password: str = ""
    enable_password: str = ""
    ssh_port: int = 22
    ap_vlan: int = 20
    vendor: str = "cisco"
    management_protocol: str = "snmp+ssh"
    snmp_version: str = "2c"
    snmp_community_ro: str = "public"
    snmp_community_rw: str | None = None
    mac_address: str | None = None
    auto_reboot_aps_enabled: bool = False
    auto_reboot_mode: str = "dry_run"

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 255:
            raise ValueError("name must be 1-255 characters")
        return v

    @field_validator("mac_address")
    @classmethod
    def validate_mac(cls, v: str | None) -> str | None:
        return _normalize_mac(v)

    @field_validator("auto_reboot_mode")
    @classmethod
    def validate_auto_reboot_mode(cls, v: str) -> str:
        normalized = v.strip().lower()
        if normalized not in {"dry_run", "live"}:
            raise ValueError("auto_reboot_mode must be 'dry_run' or 'live'")
        return normalized

    @field_validator("ip_address")
    @classmethod
    def validate_ip(cls, v: str) -> str:
        return _validate_ip(v)

    @field_validator("ssh_port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if v < 1 or v > 65535:
            raise ValueError("ssh_port must be 1-65535")
        return v

    @field_validator("ap_vlan")
    @classmethod
    def validate_vlan(cls, v: int) -> int:
        if v < 1 or v > 4094:
            raise ValueError("ap_vlan must be 1-4094")
        return v

    @field_validator("vendor")
    @classmethod
    def validate_vendor(cls, v: str) -> str:
        normalized = v.strip().lower()
        allowed = {"cisco", "dlink", "generic"}
        if normalized not in allowed:
            raise ValueError("vendor must be one of: cisco, dlink, generic")
        return normalized

    @field_validator("management_protocol")
    @classmethod
    def validate_protocol(cls, v: str) -> str:
        normalized = v.strip().lower()
        allowed = {"snmp", "ssh", "snmp+ssh"}
        if normalized not in allowed:
            raise ValueError("management_protocol must be one of: snmp, ssh, snmp+ssh")
        return normalized

    @field_validator("snmp_version")
    @classmethod
    def validate_snmp_version(cls, v: str) -> str:
        normalized = v.strip().lower()
        if normalized not in {"2c"}:
            raise ValueError("snmp_version currently supports only '2c'")
        return normalized

    @field_validator("snmp_community_ro")
    @classmethod
    def validate_snmp_ro(cls, v: str) -> str:
        value = v.strip()
        if not value or len(value) > 255:
            raise ValueError("snmp_community_ro must be 1-255 characters")
        return value

    @field_validator("snmp_community_rw")
    @classmethod
    def validate_snmp_rw(cls, v: str | None) -> str | None:
        if v is None:
            return None
        value = v.strip()
        if len(value) > 255:
            raise ValueError("snmp_community_rw must be <= 255 characters")
        return value or None


class NetworkSwitchUpdate(BaseModel):
    name: str | None = None
    ip_address: str | None = None
    ssh_username: str | None = None
    ssh_password: str | None = None
    enable_password: str | None = None
    ssh_port: int | None = None
    ap_vlan: int | None = None
    vendor: str | None = None
    management_protocol: str | None = None
    snmp_version: str | None = None
    snmp_community_ro: str | None = None
    snmp_community_rw: str | None = None
    mac_address: str | None = None
    auto_reboot_aps_enabled: bool | None = None
    auto_reboot_mode: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v or len(v) > 255:
                raise ValueError("name must be 1-255 characters")
        return v

    @field_validator("mac_address")
    @classmethod
    def validate_mac(cls, v: str | None) -> str | None:
        return _normalize_mac(v)

    @field_validator("auto_reboot_mode")
    @classmethod
    def validate_auto_reboot_mode(cls, v: str | None) -> str | None:
        if v is None:
            return None
        normalized = v.strip().lower()
        if normalized not in {"dry_run", "live"}:
            raise ValueError("auto_reboot_mode must be 'dry_run' or 'live'")
        return normalized

    @field_validator("ip_address")
    @classmethod
    def validate_ip(cls, v: str | None) -> str | None:
        if v is not None:
            return _validate_ip(v)
        return v

    @field_validator("vendor")
    @classmethod
    def validate_vendor(cls, v: str | None) -> str | None:
        if v is None:
            return None
        normalized = v.strip().lower()
        allowed = {"cisco", "dlink", "generic"}
        if normalized not in allowed:
            raise ValueError("vendor must be one of: cisco, dlink, generic")
        return normalized

    @field_validator("management_protocol")
    @classmethod
    def validate_protocol(cls, v: str | None) -> str | None:
        if v is None:
            return None
        normalized = v.strip().lower()
        allowed = {"snmp", "ssh", "snmp+ssh"}
        if normalized not in allowed:
            raise ValueError("management_protocol must be one of: snmp, ssh, snmp+ssh")
        return normalized

    @field_validator("snmp_version")
    @classmethod
    def validate_snmp_version(cls, v: str | None) -> str | None:
        if v is None:
            return None
        normalized = v.strip().lower()
        if normalized not in {"2c"}:
            raise ValueError("snmp_version currently supports only '2c'")
        return normalized

    @field_validator("snmp_community_ro", "snmp_community_rw")
    @classmethod
    def validate_communities(cls, v: str | None) -> str | None:
        if v is None:
            return None
        value = v.strip()
        if len(value) > 255:
            raise ValueError("SNMP community must be <= 255 characters")
        return value or None


class NetworkSwitchPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    ip_address: str
    ssh_username: str
    ssh_port: int = 22
    ap_vlan: int = 20
    vendor: str = "cisco"
    management_protocol: str = "snmp+ssh"
    snmp_version: str = "2c"
    model_info: str | None = None
    ios_version: str | None = None
    hostname: str | None = None
    uptime: str | None = None
    is_online: bool | None = None
    last_polled_at: datetime | None = None
    mac_address: str | None = None
    mac_status: str | None = None
    auto_reboot_aps_enabled: bool = False
    auto_reboot_mode: str = "dry_run"
    created_at: datetime


class NetworkSwitchesPublic(BaseModel):
    data: list[NetworkSwitchPublic]
    count: int


class AccessPointInfo(BaseModel):
    mac_address: str
    port: str
    vlan: int
    ip_address: str | None = None
    cdp_name: str | None = None
    cdp_platform: str | None = None
    poe_power: str | None = None
    poe_status: str | None = None
    # From the persistent AP registry (app.domains.inventory.ap_registry):
    # is_responding=False means this AP is known from a past scan but did
    # not answer CDP just now - a hang signal invisible to a plain live scan.
    is_responding: bool = True
    last_seen_at: datetime | None = None
    exclude_from_auto_reboot: bool = False


class CameraPortInfo(BaseModel):
    port: str
    vlan: int
    oper_status: str
    description: str | None = None
    poe_power: str | None = None
    poe_status: str | None = None


class AutoRebootSummary(BaseModel):
    last_cycle_at: datetime | None = None
    window_hours: int
    switches_processed: int
    aps_rebooted_ok: int
    aps_failed: int
    switches_skipped: int


class SetApExcludedRequest(BaseModel):
    excluded: bool


class SwitchPortInfo(BaseModel):
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
    port_mode: str | None = None
    access_vlan: int | None = None
    trunk_native_vlan: int | None = None
    trunk_allowed_vlans: str | None = None
    poe_enabled: bool | None = None
    poe_power_w: float | None = None
    mac_count: int | None = None


class SwitchPortsPublic(BaseModel):
    data: list[SwitchPortInfo]
    count: int


class SwitchPortAdminStateUpdate(BaseModel):
    admin_state: str

    @field_validator("admin_state")
    @classmethod
    def validate_admin_state(cls, v: str) -> str:
        normalized = v.strip().lower()
        if normalized not in {"up", "down"}:
            raise ValueError("admin_state must be 'up' or 'down'")
        return normalized


class SwitchPortDescriptionUpdate(BaseModel):
    description: str

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        value = v.strip()
        if len(value) > 255:
            raise ValueError("description must be <= 255 characters")
        return value


class SwitchPortVlanUpdate(BaseModel):
    vlan: int

    @field_validator("vlan")
    @classmethod
    def validate_vlan(cls, v: int) -> int:
        if v < 1 or v > 4094:
            raise ValueError("vlan must be 1-4094")
        return v


class SwitchPortPoeUpdate(BaseModel):
    action: str

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        normalized = v.strip().lower()
        if normalized not in {"on", "off", "cycle"}:
            raise ValueError("action must be one of: on, off, cycle")
        return normalized


class SwitchPortModeUpdate(BaseModel):
    mode: str
    access_vlan: int | None = None
    native_vlan: int | None = None
    allowed_vlans: str | None = None

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        normalized = v.strip().lower()
        if normalized not in {"access", "trunk"}:
            raise ValueError("mode must be one of: access, trunk")
        return normalized

    @field_validator("access_vlan", "native_vlan")
    @classmethod
    def validate_vlan_fields(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if v < 1 or v > 4094:
            raise ValueError("VLAN must be 1-4094")
        return v

    @field_validator("allowed_vlans")
    @classmethod
    def validate_allowed_vlans(cls, v: str | None) -> str | None:
        if v is None:
            return None
        value = v.strip()
        if not value:
            return None
        if len(value) > 255:
            raise ValueError("allowed_vlans must be <= 255 characters")
        if not re.match(r"^[0-9,\-\s]+$", value):
            raise ValueError("allowed_vlans supports digits, commas, spaces and hyphens only")
        return value


class SwitchPortSnapshotEntry(BaseModel):
    id: uuid.UUID
    captured_at: datetime
    port_count: int


class SwitchPortSnapshotHistory(BaseModel):
    data: list[SwitchPortSnapshotEntry]
    count: int
