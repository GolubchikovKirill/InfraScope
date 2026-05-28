from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class MLFeatureSnapshot(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    device_kind: str = Field(max_length=32, index=True)
    device_id: uuid.UUID | None = Field(default=None, index=True)
    device_name: str | None = Field(default=None, max_length=255, index=True)
    address: str | None = Field(default=None, max_length=255, index=True)
    is_online: bool | None = Field(default=None, index=True)
    toner_color: str | None = Field(default=None, max_length=16, index=True)
    toner_level: int | None = Field(default=None)
    toner_model: str | None = Field(default=None, max_length=128, index=True)
    source: str = Field(default="poll", max_length=32, index=True)
    hour_of_day: int = Field(default=0, index=True)
    day_of_week: int = Field(default=0, index=True)
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)


class MLModelRegistry(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    model_family: str = Field(max_length=32, index=True)
    version: str = Field(max_length=64, index=True)
    status: str = Field(default="candidate", max_length=32, index=True)
    train_rows: int = Field(default=0)
    metric_primary: float | None = Field(default=None)
    metric_secondary: float | None = Field(default=None)
    metadata_json: str | None = Field(default=None, max_length=16000)
    trained_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    activated_at: datetime | None = Field(default=None, index=True)


class MLTonerPrediction(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    printer_id: uuid.UUID | None = Field(default=None, index=True)
    printer_name: str | None = Field(default=None, max_length=255, index=True)
    toner_color: str = Field(max_length=16, index=True)
    toner_model: str | None = Field(default=None, max_length=128)
    current_level: int | None = Field(default=None)
    days_to_replacement: float | None = Field(default=None, index=True)
    predicted_replacement_at: datetime | None = Field(default=None, index=True)
    confidence: float = Field(default=0.5)
    model_version: str = Field(max_length=64, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)


class MLOfflineRiskPrediction(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    device_kind: str = Field(max_length=32, index=True)
    device_id: uuid.UUID | None = Field(default=None, index=True)
    device_name: str | None = Field(default=None, max_length=255, index=True)
    address: str | None = Field(default=None, max_length=255, index=True)
    risk_score: float = Field(default=0.0, index=True)
    risk_level: str = Field(default="low", max_length=16, index=True)
    confidence: float = Field(default=0.5)
    model_version: str = Field(max_length=64, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
