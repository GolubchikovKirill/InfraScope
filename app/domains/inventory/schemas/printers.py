from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from .common import _normalize_mac, _validate_ip

__all__ = [
    "PrinterCreate",
    "PrinterUpdate",
    "PrinterPublic",
    "PrintersPublic",
    "CartridgeStockPublic",
    "CartridgeStocksPublic",
    "CartridgeStockMovementPublic",
    "CartridgeStockMovementsPublic",
    "CartridgeStockCreate",
    "CartridgeStockUpdate",
    "CartridgeIssueRequest",
    "PrinterStatusResponse",
]


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
    reachability_reason: str | None = None
    toner_black: int | None = None
    toner_cyan: int | None = None
    toner_magenta: int | None = None
    toner_yellow: int | None = None
    toner_black_name: str | None = None
    toner_cyan_name: str | None = None
    toner_magenta_name: str | None = None
    toner_yellow_name: str | None = None
    toner_updated_at: datetime | None = None
    last_polled_at: datetime | None = None
    offline_count_24h: int = 0
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


_TONER_COLORS = {"black", "cyan", "magenta", "yellow"}


def _clean_cartridge_name(value: str) -> str:
    # split() collapses every whitespace run, NBSP included - printer-reported
    # model names arrive with U+00A0 often enough that letting it through makes
    # two visually identical cartridges into two separate catalog rows.
    value = " ".join(value.split())
    if not value:
        raise ValueError("cartridge_name must not be empty")
    if len(value) > 128:
        raise ValueError("cartridge_name must be <= 128 characters")
    return value


def _clean_toner_color(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip().lower()
    if not value:
        return None
    if value not in _TONER_COLORS:
        raise ValueError("toner_color must be one of: black, cyan, magenta, yellow")
    return value


def _clean_compatible_models(value: str | None) -> str:
    value = " ".join((value or "").split())
    if len(value) > 1024:
        raise ValueError("compatible_printer_models must be <= 1024 characters")
    return value


def _clean_note(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > 512:
        raise ValueError("note must be <= 512 characters")
    return value


class CartridgeStockCreate(BaseModel):
    cartridge_name: str
    toner_color: str | None = None
    compatible_printer_models: str = ""
    quantity_on_hand: int = 0
    minimum_stock: int = 0
    note: str | None = None

    @field_validator("cartridge_name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _clean_cartridge_name(value)

    @field_validator("toner_color")
    @classmethod
    def validate_color(cls, value: str | None) -> str | None:
        return _clean_toner_color(value)

    @field_validator("compatible_printer_models")
    @classmethod
    def validate_models(cls, value: str | None) -> str:
        return _clean_compatible_models(value)

    @field_validator("quantity_on_hand", "minimum_stock")
    @classmethod
    def validate_non_negative_int(cls, value: int) -> int:
        if value < 0:
            raise ValueError("value must be non-negative")
        return value

    @field_validator("note")
    @classmethod
    def validate_note(cls, value: str | None) -> str | None:
        return _clean_note(value)


class CartridgeStockUpdate(BaseModel):
    cartridge_name: str | None = None
    toner_color: str | None = None
    compatible_printer_models: str | None = None
    quantity_on_hand: int | None = None
    minimum_stock: int | None = None
    is_active: bool | None = None
    note: str | None = None

    @field_validator("cartridge_name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        return None if value is None else _clean_cartridge_name(value)

    @field_validator("toner_color")
    @classmethod
    def validate_color(cls, value: str | None) -> str | None:
        return _clean_toner_color(value)

    @field_validator("compatible_printer_models")
    @classmethod
    def validate_models(cls, value: str | None) -> str | None:
        return None if value is None else _clean_compatible_models(value)

    @field_validator("quantity_on_hand", "minimum_stock")
    @classmethod
    def validate_non_negative_int(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("value must be non-negative")
        return value

    @field_validator("note")
    @classmethod
    def validate_note(cls, value: str | None) -> str | None:
        return _clean_note(value)


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
        return _clean_note(value)


class PrinterStatusResponse(BaseModel):
    is_online: bool
    status: str
    toner_black: int | None = None
    toner_cyan: int | None = None
    toner_magenta: int | None = None
    toner_yellow: int | None = None
    sys_description: str | None = None
