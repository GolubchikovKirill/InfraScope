from __future__ import annotations

from pydantic import BaseModel

from .scanner import ScanProgress

__all__ = ["DiscoveredNetworkDevice", "DiscoveryResults"]


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
