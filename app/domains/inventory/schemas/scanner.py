from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

__all__ = [
    "ScanRequest",
    "DiscoveredDevice",
    "ScanProgress",
    "ScanResults",
    "SmartNetworkSearchRequest",
    "SmartNetworkCandidatePublic",
    "SmartNetworkSearchPublic",
    "MacRediscoveryRequest",
    "MacRediscoveryItem",
    "MacRediscoveryResponse",
]


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
