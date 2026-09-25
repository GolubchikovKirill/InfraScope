from __future__ import annotations

import uuid
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.core.config import settings
from app.domains.ml.models import MLModelRegistry, MLOfflineRiskPrediction, MLTonerPrediction
from app.domains.ml.schemas import (
    MLModelsStatusPublic,
    MLModelStatusPublic,
    MLOfflineRiskPredictionPublic,
    MLOfflineRiskPredictionsPublic,
    MLTonerPredictionPublic,
    MLTonerPredictionsPublic,
)
from app.domains.shared.schemas import Message
from app.observability.metrics import worker_tasks_enqueued_total
from app.services.cache import get_cached_model, set_cached_model
from app.worker.tasks import ml_run_cycle_task

router = APIRouter(tags=["ml"])
CACHE_TTL = 30


@router.get("/predictions/toner", response_model=MLTonerPredictionsPublic)
async def read_toner_predictions(
    session: SessionDep,
    current_user: CurrentUser,
    printer_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
) -> MLTonerPredictionsPublic:
    del current_user
    cache_key = f"ml_toner:{printer_id or ''}:{limit}"
    if cached := await get_cached_model(cache_key, MLTonerPredictionsPublic):
        return cached

    statement = select(MLTonerPrediction).order_by(col(MLTonerPrediction.created_at).desc())
    if printer_id is not None:
        statement = statement.where(MLTonerPrediction.printer_id == printer_id)
    rows = session.exec(statement.limit(limit)).all()
    result = MLTonerPredictionsPublic(data=cast(list[MLTonerPredictionPublic], list(rows)), count=len(rows))
    await set_cached_model(cache_key, result, ttl=CACHE_TTL)
    return result


@router.get("/predictions/offline-risk", response_model=MLOfflineRiskPredictionsPublic)
async def read_offline_risk_predictions(
    session: SessionDep,
    current_user: CurrentUser,
    device_kind: str | None = Query(default=None),
    limit: int = Query(default=300, ge=1, le=1000),
) -> MLOfflineRiskPredictionsPublic:
    del current_user
    cache_key = f"ml_offline_risk:{device_kind or ''}:{limit}"
    if cached := await get_cached_model(cache_key, MLOfflineRiskPredictionsPublic):
        return cached

    statement = select(MLOfflineRiskPrediction).order_by(col(MLOfflineRiskPrediction.created_at).desc())
    if device_kind is not None:
        statement = statement.where(MLOfflineRiskPrediction.device_kind == device_kind)
    rows = session.exec(statement.limit(limit)).all()
    result = MLOfflineRiskPredictionsPublic(
        data=cast(list[MLOfflineRiskPredictionPublic], list(rows)), count=len(rows)
    )
    await set_cached_model(cache_key, result, ttl=CACHE_TTL)
    return result


@router.get("/models/status", response_model=MLModelsStatusPublic)
async def read_model_status(
    session: SessionDep,
    current_user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
) -> MLModelsStatusPublic:
    del current_user
    cache_key = f"ml_models_status:{limit}"
    if cached := await get_cached_model(cache_key, MLModelsStatusPublic):
        return cached

    rows = session.exec(
        select(MLModelRegistry).order_by(col(MLModelRegistry.trained_at).desc()).limit(limit)
    ).all()
    data = [
        MLModelStatusPublic(
            model_family=row.model_family,
            version=row.version,
            status=row.status,
            train_rows=row.train_rows,
            metric_primary=row.metric_primary,
            metric_secondary=row.metric_secondary,
            trained_at=row.trained_at,
            activated_at=row.activated_at,
        )
        for row in rows
    ]
    result = MLModelsStatusPublic(data=data, count=len(data))
    await set_cached_model(cache_key, result, ttl=CACHE_TTL)
    return result


@router.post("/run-cycle", dependencies=[Depends(get_current_active_superuser)], response_model=Message)
async def run_ml_cycle(current_user: CurrentUser) -> Message:
    del current_user
    if not settings.ML_ENABLED:
        raise HTTPException(status_code=503, detail="Prediction service is disabled")
    try:
        ml_run_cycle_task.delay()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Task queue unavailable: {exc}") from exc
    worker_tasks_enqueued_total.labels(operation="ml_run_cycle").inc()
    return Message(message="Prediction cycle started")
