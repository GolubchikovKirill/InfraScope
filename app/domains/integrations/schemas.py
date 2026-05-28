from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator


class QRGeneratorRequest(BaseModel):
    db_mode: Literal["duty_free", "duty_paid", "both"] = "duty_free"
    airport_code: str = "4007"
    surnames: str | None = None
    add_login: bool = False

    @field_validator("airport_code")
    @classmethod
    def validate_required_text(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("Field is required")
        if len(value) > 255:
            raise ValueError("Field is too long")
        return value

    @field_validator("surnames")
    @classmethod
    def normalize_surnames(cls, v: str | None) -> str | None:
        if v is None:
            return None
        value = v.strip()
        if not value:
            return None
        if len(value) > 1000:
            raise ValueError("surnames is too long")
        return value


class BoardingPassRequest(BaseModel):
    format: Literal["aztec", "pdf417"] = "aztec"
    first_name: str | None = None
    last_name: str | None = None
    booking_ref: str | None = None
    from_code: str | None = None
    to_code: str | None = None
    flight_operator: str | None = None
    flight_number: str | None = None
    flight_date: str | None = None
    day_in_year: str | None = None
    travel_class: str | None = None
    seat: str | None = None
    boarding_index: str | None = None
    raw_data: str | None = None

    @field_validator(
        "first_name",
        "last_name",
        "booking_ref",
        "from_code",
        "to_code",
        "flight_operator",
        "flight_number",
        "flight_date",
        "day_in_year",
        "travel_class",
        "seat",
        "boarding_index",
        "raw_data",
    )
    @classmethod
    def normalize_optional_text(cls, v: str | None) -> str | None:
        if v is None:
            return None
        value = v.strip()
        if not value:
            return None
        if len(value) > 512:
            raise ValueError("Field is too long")
        return value

    @field_validator("from_code", "to_code")
    @classmethod
    def validate_airport_codes(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if len(v) != 3 or not re.match(r"^[A-Za-z]{3}$", v):
            raise ValueError("Airport code must be exactly 3 letters")
        return v.upper()

    @model_validator(mode="after")
    def validate_mode_requirements(self) -> BoardingPassRequest:
        if self.raw_data:
            return self
        if bool(self.from_code) != bool(self.to_code):
            raise ValueError("from_code and to_code must be provided together")
        return self


class OneCExchangeByBarcodeRequest(BaseModel):
    target: Literal["duty_free", "duty_paid"] = "duty_free"
    barcode: str
    cash_register_identifier_kind: Literal[
        "hostname",
        "kkm_number",
        "serial_number",
        "inventory_number",
        "cash_number",
    ] = "kkm_number"
    cash_register_identifiers: list[str] = []
    cash_register_hostnames: list[str] = []
    source: str = "infrascope"

    @field_validator("barcode")
    @classmethod
    def validate_barcode(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("barcode is required")
        if len(value) > 64:
            raise ValueError("barcode is too long")
        return value

    @field_validator("cash_register_hostnames")
    @classmethod
    def normalize_hosts(cls, v: list[str]) -> list[str]:
        result: list[str] = []
        for item in v:
            host = item.strip()
            if host:
                result.append(host)
        return result

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        value = v.strip()
        if not value:
            return "infrascope"
        if len(value) > 64:
            raise ValueError("source is too long")
        return value

    @field_validator("cash_register_identifiers")
    @classmethod
    def normalize_identifiers(cls, v: list[str]) -> list[str]:
        result: list[str] = []
        for item in v:
            identifier = item.strip()
            if identifier:
                result.append(identifier)
        return result

    @model_validator(mode="after")
    def migrate_legacy_hosts(self) -> OneCExchangeByBarcodeRequest:
        if not self.cash_register_identifiers and self.cash_register_hostnames:
            self.cash_register_identifiers = list(self.cash_register_hostnames)
            self.cash_register_identifier_kind = "hostname"
        return self


class OneCExchangeByBarcodeResponse(BaseModel):
    target: Literal["duty_free", "duty_paid"] | None = None
    ok: bool
    message: str
    status_code: int | None = None
    request_id: str | None = None
    payload: dict | None = None
    error_kind: Literal["validation", "integration", "timeout", "config", "unknown"] | None = None
