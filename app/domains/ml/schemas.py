from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MLTonerPredictionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    printer_id: uuid.UUID | None = None
    printer_name: str | None = None
    toner_color: str
    toner_model: str | None = None
    current_level: int | None = None
    days_to_replacement: float | None = None
    predicted_replacement_at: datetime | None = None
    confidence: float
    model_version: str
    created_at: datetime


class MLTonerPredictionsPublic(BaseModel):
    data: list[MLTonerPredictionPublic]
    count: int


class MLOfflineRiskPredictionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    device_kind: str
    device_id: uuid.UUID | None = None
    device_name: str | None = None
    address: str | None = None
    risk_score: float
    risk_level: str
    confidence: float
    model_version: str
    created_at: datetime


class MLOfflineRiskPredictionsPublic(BaseModel):
    data: list[MLOfflineRiskPredictionPublic]
    count: int


class MLModelStatusPublic(BaseModel):
    model_family: str
    version: str
    status: str
    train_rows: int
    metric_primary: float | None = None
    metric_secondary: float | None = None
    trained_at: datetime
    activated_at: datetime | None = None


class MLModelsStatusPublic(BaseModel):
    data: list[MLModelStatusPublic]
    count: int
