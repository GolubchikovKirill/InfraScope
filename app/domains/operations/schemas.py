from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class EventLogPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    severity: str
    category: str
    event_type: str
    message: str
    device_kind: str | None = None
    device_name: str | None = None
    ip_address: str | None = None
    created_at: datetime


class EventLogsPublic(BaseModel):
    data: list[EventLogPublic]
    count: int


class CashRegisterCreate(BaseModel):
    kkm_number: str
    store_number: str | None = None
    store_code: str | None = None
    serial_number: str | None = None
    inventory_number: str | None = None
    terminal_id_rs: str | None = None
    terminal_id_sber: str | None = None
    windows_version: str | None = None
    kkm_type: str = "retail"
    cash_number: str | None = None
    hostname: str
    comment: str | None = None

    @field_validator("kkm_number", "hostname")
    @classmethod
    def validate_required_short_text(cls, v: str) -> str:
        value = v.strip()
        if not value or len(value) > 255:
            raise ValueError("Field must be 1-255 characters")
        return value

    @field_validator("kkm_type")
    @classmethod
    def validate_kkm_type(cls, v: str) -> str:
        value = v.strip().lower()
        if value not in {"retail", "shtrih"}:
            raise ValueError("kkm_type must be 'retail' or 'shtrih'")
        return value

    @field_validator(
        "store_number",
        "store_code",
        "serial_number",
        "inventory_number",
        "terminal_id_rs",
        "terminal_id_sber",
        "windows_version",
        "cash_number",
        "comment",
    )
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


class CashRegisterUpdate(BaseModel):
    kkm_number: str | None = None
    store_number: str | None = None
    store_code: str | None = None
    serial_number: str | None = None
    inventory_number: str | None = None
    terminal_id_rs: str | None = None
    terminal_id_sber: str | None = None
    windows_version: str | None = None
    kkm_type: str | None = None
    cash_number: str | None = None
    hostname: str | None = None
    comment: str | None = None

    @field_validator("kkm_number", "hostname")
    @classmethod
    def validate_required_short_text(cls, v: str | None) -> str | None:
        if v is None:
            return None
        value = v.strip()
        if not value or len(value) > 255:
            raise ValueError("Field must be 1-255 characters")
        return value

    @field_validator("kkm_type")
    @classmethod
    def validate_kkm_type(cls, v: str | None) -> str | None:
        if v is None:
            return None
        value = v.strip().lower()
        if value not in {"retail", "shtrih"}:
            raise ValueError("kkm_type must be 'retail' or 'shtrih'")
        return value

    @field_validator(
        "store_number",
        "store_code",
        "serial_number",
        "inventory_number",
        "terminal_id_rs",
        "terminal_id_sber",
        "windows_version",
        "cash_number",
        "comment",
    )
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


class CashRegisterPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kkm_number: str
    store_number: str | None = None
    store_code: str | None = None
    serial_number: str | None = None
    inventory_number: str | None = None
    terminal_id_rs: str | None = None
    terminal_id_sber: str | None = None
    windows_version: str | None = None
    kkm_type: str
    cash_number: str | None = None
    hostname: str
    comment: str | None = None
    is_online: bool | None = None
    reachability_reason: str | None = None
    last_polled_at: datetime | None = None
    created_at: datetime


class CashRegistersPublic(BaseModel):
    data: list[CashRegisterPublic]
    count: int


class GeneralSettingsPublic(BaseModel):
    scan_subnet: str
    scan_ports: str
    dns_search_suffixes: str


class GeneralSettingsUpdate(BaseModel):
    scan_subnet: str | None = None
    scan_ports: str | None = None
    dns_search_suffixes: str | None = None

    @field_validator("scan_subnet", "scan_ports", "dns_search_suffixes")
    @classmethod
    def normalize_text(cls, v: str | None) -> str | None:
        if v is None:
            return None
        value = v.strip()
        if not value:
            raise ValueError("Value cannot be empty")
        if len(value) > 2000:
            raise ValueError("Value is too long")
        return value


class ServiceFlowLinkPublic(BaseModel):
    label: str
    url: str


class ServiceFlowNodePublic(BaseModel):
    id: str
    label: str
    kind: str
    status: str
    req_rate: float | None = None
    error_rate: float | None = None
    p95_latency_ms: float | None = None
    last_seen: datetime | None = None
    links: list[ServiceFlowLinkPublic] = []


class ServiceFlowEdgePublic(BaseModel):
    source: str
    target: str
    transport: str
    operation: str
    status: str
    req_rate: float | None = None
    error_rate: float | None = None
    p95_latency_ms: float | None = None


class ServiceFlowRecentEventPublic(BaseModel):
    id: uuid.UUID
    created_at: datetime
    severity: str
    category: str
    event_type: str
    message: str
    device_kind: str | None = None
    device_name: str | None = None
    ip_address: str | None = None
    trace_id: str | None = None


class ServiceFlowMapPublic(BaseModel):
    generated_at: datetime
    nodes: list[ServiceFlowNodePublic]
    edges: list[ServiceFlowEdgePublic]
    recent_events: list[ServiceFlowRecentEventPublic]


class ServiceFlowTimeseriesPointPublic(BaseModel):
    timestamp: datetime
    req_rate: float | None = None
    error_rate: float | None = None
    p95_latency_ms: float | None = None


class ServiceFlowTimeseriesPublic(BaseModel):
    entity: str
    points: list[ServiceFlowTimeseriesPointPublic]
