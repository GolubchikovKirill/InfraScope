from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class EventLog(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    severity: str = Field(default="info", max_length=16, index=True)
    category: str = Field(default="system", max_length=64, index=True)
    event_type: str = Field(max_length=128, index=True)
    message: str = Field(max_length=1024)
    device_kind: str | None = Field(default=None, max_length=32, index=True)
    device_name: str | None = Field(default=None, max_length=255)
    ip_address: str | None = Field(default=None, max_length=255, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)


class CashRegister(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    kkm_number: str = Field(max_length=64, index=True)
    store_number: str | None = Field(default=None, max_length=64, index=True)
    store_code: str | None = Field(default=None, max_length=64, index=True)
    serial_number: str | None = Field(default=None, max_length=128, index=True)
    inventory_number: str | None = Field(default=None, max_length=128, index=True)
    terminal_id_rs: str | None = Field(default=None, max_length=128, index=True)
    terminal_id_sber: str | None = Field(default=None, max_length=128, index=True)
    windows_version: str | None = Field(default=None, max_length=128)
    kkm_type: str = Field(default="retail", max_length=16, index=True)
    cash_number: str | None = Field(default=None, max_length=64, index=True)
    hostname: str = Field(max_length=255, index=True)
    netsupport_target: str | None = Field(default=None, max_length=255, index=True)
    comment: str | None = Field(default=None, max_length=1024)

    is_online: bool | None = Field(default=None, index=True)
    reachability_reason: str | None = Field(default=None, max_length=64)
    last_polled_at: datetime | None = Field(default=None, index=True)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    updated_at: datetime | None = Field(default=None)


class AppSetting(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    key: str = Field(max_length=128, unique=True, index=True)
    value: str = Field(max_length=4000)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
