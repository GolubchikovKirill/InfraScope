from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domains.shared.schemas import _IP_PATTERN, validate_ip_address


def _validate_ip(v: str) -> str:
    return validate_ip_address(v)


def _normalize_mac(v: str | None) -> str | None:
    if v is None:
        return None
    compact = re.sub(r"[^0-9a-fA-F]", "", v.strip())
    if not compact:
        return None
    if not re.fullmatch(r"[0-9a-fA-F]{12}", compact):
        raise ValueError("mac_address must contain 12 hex digits")
    return ":".join(compact[i : i + 2].lower() for i in range(0, 12, 2))


class PrinterCreate(BaseModel):
    printer_type: str = "laser"
    connection_type: str = "ip"
    store_name: str
    model: str
    ip_address: str | None = None
    mac_address: str | None = None
    snmp_community: str = "public"
    host_pc: str | None = None
    toner_black_name: str | None = None
    toner_cyan_name: str | None = None
    toner_magenta_name: str | None = None
    toner_yellow_name: str | None = None

    @field_validator("store_name")
    @classmethod
    def validate_store_name(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 255:
            raise ValueError("store_name must be 1-255 characters")
        return v

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 255:
            raise ValueError("model must be 1-255 characters")
        return v

    @field_validator("snmp_community")
    @classmethod
    def validate_community(cls, v: str) -> str:
        if len(v) > 255:
            raise ValueError("snmp_community must be <= 255 characters")
        return v

    @field_validator("ip_address")
    @classmethod
    def validate_ip(cls, v: str | None) -> str | None:
        if v is not None:
            return _validate_ip(v)
        return v

    @field_validator("mac_address")
    @classmethod
    def validate_mac(cls, v: str | None) -> str | None:
        return _normalize_mac(v)

    @field_validator("printer_type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ("laser", "label"):
            raise ValueError("printer_type must be 'laser' or 'label'")
        return v

    @field_validator("connection_type")
    @classmethod
    def validate_connection_type(cls, v: str) -> str:
        if v not in ("ip", "usb"):
            raise ValueError("connection_type must be 'ip' or 'usb'")
        return v

    @field_validator("host_pc")
    @classmethod
    def validate_host_pc(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if len(v) > 255:
                raise ValueError("host_pc must be <= 255 characters")
            if not v:
                return None
        return v

    @field_validator("toner_black_name", "toner_cyan_name", "toner_magenta_name", "toner_yellow_name")
    @classmethod
    def validate_toner_names(cls, v: str | None) -> str | None:
        if v is None:
            return None
        value = v.strip()
        if not value:
            return None
        if len(value) > 128:
            raise ValueError("toner name must be <= 128 characters")
        return value

    @model_validator(mode="after")
    def check_ip_required_for_ip_type(self) -> PrinterCreate:
        if self.connection_type == "ip" and not self.ip_address:
            raise ValueError("ip_address is required when connection_type is 'ip'")
        return self


class PrinterUpdate(BaseModel):
    store_name: str | None = None
    model: str | None = None
    ip_address: str | None = None
    mac_address: str | None = None
    snmp_community: str | None = None
    host_pc: str | None = None
    toner_black_name: str | None = None
    toner_cyan_name: str | None = None
    toner_magenta_name: str | None = None
    toner_yellow_name: str | None = None

    @field_validator("store_name")
    @classmethod
    def validate_store_name(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v or len(v) > 255:
                raise ValueError("store_name must be 1-255 characters")
        return v

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v or len(v) > 255:
                raise ValueError("model must be 1-255 characters")
        return v

    @field_validator("ip_address")
    @classmethod
    def validate_ip(cls, v: str | None) -> str | None:
        if v is not None:
            return _validate_ip(v)
        return v

    @field_validator("mac_address")
    @classmethod
    def validate_mac(cls, v: str | None) -> str | None:
        return _normalize_mac(v)

    @field_validator("host_pc")
    @classmethod
    def validate_host_pc(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if len(v) > 255:
                raise ValueError("host_pc must be <= 255 characters")
            if not v:
                return None
        return v

    @field_validator("toner_black_name", "toner_cyan_name", "toner_magenta_name", "toner_yellow_name")
    @classmethod
    def validate_toner_names(cls, v: str | None) -> str | None:
        if v is None:
            return None
        value = v.strip()
        if not value:
            return None
        if len(value) > 128:
            raise ValueError("toner name must be <= 128 characters")
        return value


class PrinterPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    printer_type: str = "laser"
    connection_type: str = "ip"
    store_name: str
    model: str
    ip_address: str | None = None
    mac_address: str | None = None
    mac_status: str | None = None
    host_pc: str | None = None
    is_online: bool | None = None
    status: str | None = None
    toner_black: int | None = None
    toner_cyan: int | None = None
    toner_magenta: int | None = None
    toner_yellow: int | None = None
    toner_black_name: str | None = None
    toner_cyan_name: str | None = None
    toner_magenta_name: str | None = None
    toner_yellow_name: str | None = None
    last_polled_at: datetime | None = None
    created_at: datetime


class PrintersPublic(BaseModel):
    data: list[PrinterPublic]
    count: int


class CartridgeStockPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    cartridge_name: str
    toner_color: str | None = None
    compatible_printer_models: str
    printer_count: int
    quantity_on_hand: int
    minimum_stock: int
    is_active: bool
    last_synced_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None


class CartridgeStocksPublic(BaseModel):
    data: list[CartridgeStockPublic]
    count: int


class CartridgeStockMovementPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    stock_id: uuid.UUID
    delta: int
    reason: str
    note: str | None = None
    created_by: str | None = None
    created_at: datetime


class CartridgeStockMovementsPublic(BaseModel):
    data: list[CartridgeStockMovementPublic]
    count: int


class CartridgeStockUpdate(BaseModel):
    quantity_on_hand: int | None = None
    minimum_stock: int | None = None
    note: str | None = None

    @field_validator("quantity_on_hand", "minimum_stock")
    @classmethod
    def validate_non_negative_int(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("value must be non-negative")
        return value

    @field_validator("note")
    @classmethod
    def validate_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if len(value) > 512:
            raise ValueError("note must be <= 512 characters")
        return value


class CartridgeIssueRequest(BaseModel):
    quantity: int = 1
    note: str | None = None

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, value: int) -> int:
        if value < 1 or value > 1000:
            raise ValueError("quantity must be between 1 and 1000")
        return value

    @field_validator("note")
    @classmethod
    def validate_issue_note(cls, value: str | None) -> str | None:
        return CartridgeStockUpdate.validate_note(value)


class PrinterStatusResponse(BaseModel):
    is_online: bool
    status: str
    toner_black: int | None = None
    toner_cyan: int | None = None
    toner_magenta: int | None = None
    toner_yellow: int | None = None
    sys_description: str | None = None


# ── Scanner schemas ──────────────────────────────────────────────


class ScanRequest(BaseModel):
    subnet: str
    ports: str = "9100,631,80,443"

    @field_validator("subnet")
    @classmethod
    def validate_subnet(cls, v: str) -> str:
        import ipaddress

        parts = [p.strip() for p in v.split(",") if p.strip()]
        if not parts:
            raise ValueError("At least one subnet is required")
        if len(parts) > 10:
            raise ValueError("Maximum 10 subnets allowed")
        for part in parts:
            try:
                net = ipaddress.ip_network(part, strict=False)
                if net.prefixlen < 16:
                    raise ValueError(f"Subnet {part} too large (min /16)")
            except ValueError as e:
                if "too large" in str(e):
                    raise
                raise ValueError(f"Invalid subnet: {part} (expected CIDR, e.g. 10.10.98.0/24)")
        return v

    @field_validator("ports")
    @classmethod
    def validate_ports(cls, v: str) -> str:
        parts = [p.strip() for p in v.split(",") if p.strip()]
        if not parts:
            raise ValueError("At least one port is required")
        if len(parts) > 20:
            raise ValueError("Maximum 20 ports allowed")
        for part in parts:
            try:
                port = int(part)
                if port < 1 or port > 65535:
                    raise ValueError(f"Port {port} out of range (1-65535)")
            except ValueError as e:
                if "out of range" in str(e):
                    raise
                raise ValueError(f"Invalid port: {part} (must be integer)")
        return v


class DiscoveredDevice(BaseModel):
    ip: str
    mac: str | None = None
    open_ports: list[int] = []
    hostname: str | None = None
    is_known: bool = False
    known_printer_id: str | None = None
    ip_changed: bool = False
    old_ip: str | None = None


class ScanProgress(BaseModel):
    status: str  # "idle" | "running" | "done" | "error"
    scanned: int = 0
    total: int = 0
    found: int = 0
    message: str | None = None


class ScanResults(BaseModel):
    progress: ScanProgress
    devices: list[DiscoveredDevice] = []


class SmartNetworkSearchRequest(BaseModel):
    subnet: str | None = None
    ports: str | None = None
    hostname_contains: str | None = None
    limit: int = 200

    @field_validator("subnet")
    @classmethod
    def validate_optional_subnet(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return ScanRequest.validate_subnet(v)

    @field_validator("ports")
    @classmethod
    def validate_optional_ports(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return ScanRequest.validate_ports(v)

    @field_validator("hostname_contains")
    @classmethod
    def normalize_hostname_contains(cls, v: str | None) -> str | None:
        if v is None:
            return None
        value = v.strip()
        if not value:
            return None
        if len(value) > 128:
            raise ValueError("hostname_contains must be <= 128 characters")
        return value

    @field_validator("limit")
    @classmethod
    def validate_limit(cls, v: int) -> int:
        if v < 1 or v > 2000:
            raise ValueError("limit must be between 1 and 2000")
        return v


class SmartNetworkCandidatePublic(BaseModel):
    ip: str
    hostname: str | None = None
    open_ports: list[int]
    confidence: str
    reason: str


class SmartNetworkSearchPublic(BaseModel):
    data: list[SmartNetworkCandidatePublic]
    count: int
    used_subnet: str
    used_ports: str


class MacRediscoveryRequest(BaseModel):
    device_kinds: list[Literal["printer", "media_player"]] = Field(
        default_factory=lambda: ["printer", "media_player"]
    )
    apply: bool = True
    subnets: list[str] = Field(default_factory=list)

    @field_validator("device_kinds")
    @classmethod
    def validate_device_kinds(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("device_kinds must not be empty")
        return list(dict.fromkeys(v))

    @field_validator("subnets")
    @classmethod
    def validate_subnets(cls, v: list[str]) -> list[str]:
        if len(v) > 10:
            raise ValueError("Maximum 10 subnets allowed")
        for subnet in v:
            ScanRequest.validate_subnet(subnet)
        return v


class MacRediscoveryItem(BaseModel):
    device_kind: str
    id: str
    name: str
    mac_address: str
    old_ip: str | None = None
    new_ip: str | None = None
    status: Literal["updated", "found", "unchanged", "not_found", "conflict"]
    message: str | None = None


class MacRediscoveryResponse(BaseModel):
    data: list[MacRediscoveryItem]
    count: int
    updated: int


class ComputerCreate(BaseModel):
    hostname: str
    location: str | None = None
    comment: str | None = None

    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, v: str) -> str:
        value = v.strip()
        if not value or len(value) > 255:
            raise ValueError("hostname must be 1-255 characters")
        return value

    @field_validator("location", "comment")
    @classmethod
    def normalize_optional_text(cls, v: str | None) -> str | None:
        if v is None:
            return None
        value = v.strip()
        if not value:
            return None
        if len(value) > 1024:
            raise ValueError("Field is too long")
        return value


class ComputerUpdate(BaseModel):
    hostname: str | None = None
    location: str | None = None
    comment: str | None = None

    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, v: str | None) -> str | None:
        if v is None:
            return None
        value = v.strip()
        if not value or len(value) > 255:
            raise ValueError("hostname must be 1-255 characters")
        return value

    @field_validator("location", "comment")
    @classmethod
    def normalize_optional_text(cls, v: str | None) -> str | None:
        if v is None:
            return None
        value = v.strip()
        if not value:
            return None
        if len(value) > 1024:
            raise ValueError("Field is too long")
        return value


class ComputerPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hostname: str
    location: str | None = None
    comment: str | None = None
    is_online: bool | None = None
    reachability_reason: str | None = None
    last_polled_at: datetime | None = None
    created_at: datetime


class ComputersPublic(BaseModel):
    data: list[ComputerPublic]
    count: int


# ── Generic network discovery schemas ────────────────────────────


class DiscoveredNetworkDevice(BaseModel):
    ip: str
    mac: str | None = None
    open_ports: list[int] = []
    hostname: str | None = None
    model_info: str | None = None
    vendor: str | None = None
    device_kind: str | None = None
    is_known: bool = False
    known_device_id: str | None = None
    ip_changed: bool = False
    old_ip: str | None = None


class DiscoveryResults(BaseModel):
    progress: ScanProgress
    devices: list[DiscoveredNetworkDevice] = []


# ── NetworkSwitch schemas ───────────────────────────────────────


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


# ── MediaPlayer schemas ─────────────────────────────────────────


_HOSTNAME_PATTERN = r"^[a-zA-Z0-9]([a-zA-Z0-9\-\.]{0,253}[a-zA-Z0-9])?$"


def _validate_ip_or_hostname(v: str) -> str:
    v = v.strip()
    if not v or len(v) > 255:
        raise ValueError("Address must be 1-255 characters")
    if re.match(_IP_PATTERN, v):
        parts = v.split(".")
        if any(int(p) > 255 for p in parts):
            raise ValueError("IP address octets must be 0-255")
        return v
    if re.match(_HOSTNAME_PATTERN, v):
        return v
    raise ValueError("Must be a valid IP address or hostname")


class MediaPlayerCreate(BaseModel):
    device_type: str
    name: str
    model: str = ""
    ip_address: str
    hostname: str | None = None
    mac_address: str | None = None

    @field_validator("device_type")
    @classmethod
    def validate_device_type(cls, v: str) -> str:
        if v not in ("nettop", "iconbit", "twix"):
            raise ValueError("device_type must be 'nettop', 'iconbit', or 'twix'")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 255:
            raise ValueError("name must be 1-255 characters")
        return v

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        v = v.strip()
        if len(v) > 255:
            raise ValueError("model must be <= 255 characters")
        return v

    @field_validator("ip_address")
    @classmethod
    def validate_ip(cls, v: str) -> str:
        return _validate_ip_or_hostname(v)

    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, v: str | None) -> str | None:
        if v is None:
            return None
        value = v.strip()
        if not value:
            return None
        if len(value) > 255:
            raise ValueError("hostname must be <= 255 characters")
        if not re.match(_HOSTNAME_PATTERN, value):
            raise ValueError("hostname format is invalid")
        return value

    @field_validator("mac_address")
    @classmethod
    def validate_mac(cls, v: str | None) -> str | None:
        return _normalize_mac(v)

    @model_validator(mode="after")
    def set_default_model(self) -> MediaPlayerCreate:
        if not self.model:
            defaults = {"nettop": "Неттоп", "iconbit": "Iconbit", "twix": "Twix"}
            self.model = defaults.get(self.device_type, self.device_type)
        return self


class MediaPlayerUpdate(BaseModel):
    name: str | None = None
    model: str | None = None
    ip_address: str | None = None
    hostname: str | None = None
    mac_address: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v or len(v) > 255:
                raise ValueError("name must be 1-255 characters")
        return v

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if len(v) > 255:
                raise ValueError("model must be <= 255 characters")
        return v

    @field_validator("ip_address")
    @classmethod
    def validate_ip(cls, v: str | None) -> str | None:
        if v is not None:
            return _validate_ip_or_hostname(v)
        return v

    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, v: str | None) -> str | None:
        if v is None:
            return None
        value = v.strip()
        if not value:
            return None
        if len(value) > 255:
            raise ValueError("hostname must be <= 255 characters")
        if not re.match(_HOSTNAME_PATTERN, value):
            raise ValueError("hostname format is invalid")
        return value

    @field_validator("mac_address")
    @classmethod
    def validate_mac(cls, v: str | None) -> str | None:
        return _normalize_mac(v)


class MediaPlayerPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    device_type: str
    name: str
    model: str
    ip_address: str
    mac_address: str | None = None
    is_online: bool | None = None
    hostname: str | None = None
    os_info: str | None = None
    uptime: str | None = None
    open_ports: str | None = None
    last_polled_at: datetime | None = None
    created_at: datetime


class MediaPlayersPublic(BaseModel):
    data: list[MediaPlayerPublic]
    count: int
