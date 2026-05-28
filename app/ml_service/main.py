from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.core.readiness import build_readiness_response, check_database, check_redis
from app.core.redis import get_redis
from app.domains.ml.models import MLModelRegistry
from app.ml.pipeline import run_scoring_cycle, run_training_cycle
from app.observability.metrics import ml_train_runs_total
from app.observability.tracing import setup_tracing

logger = logging.getLogger(__name__)


class _SchedulerState:
    def __init__(self) -> None:
        self.last_training_day: str | None = None
        self.last_score_ts: float = 0.0
        self.task: asyncio.Task | None = None


state = _SchedulerState()


async def _run_training() -> dict:
    try:
        with Session(engine) as session:
            result = run_training_cycle(session, min_train_rows=settings.ML_MIN_TRAIN_ROWS)
        logger.info("Prediction training completed: %s", result)
        return result
    except Exception:
        ml_train_runs_total.labels(model_family="toner_forecast", result="error").inc()
        ml_train_runs_total.labels(model_family="offline_risk", result="error").inc()
        raise


async def _run_scoring() -> dict:
    with Session(engine) as session:
        result = run_scoring_cycle(session)
    logger.info("Prediction scoring completed: %s", result)
    return result


async def _scheduler_loop() -> None:
    while True:
        now = datetime.now(UTC)
        today = now.strftime("%Y-%m-%d")
        try:
            if settings.ML_ENABLED and now.hour == settings.ML_RETRAIN_HOUR_UTC and state.last_training_day != today:
                await _run_training()
                await _run_scoring()
                state.last_training_day = today
                state.last_score_ts = now.timestamp()
            elif settings.ML_ENABLED and (
                now.timestamp() - state.last_score_ts >= max(settings.ML_SCORE_INTERVAL_MINUTES, 1) * 60
            ):
                await _run_scoring()
                state.last_score_ts = now.timestamp()
        except Exception as exc:  # pragma: no cover - defensive runtime loop
            logger.exception("Prediction scheduler iteration failed: %s", exc)
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.task = asyncio.create_task(_scheduler_loop(), name="ml-scheduler")
    yield
    if state.task:
        state.task.cancel()
        try:
            await state.task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="InfraScope Prediction Service", lifespan=lifespan)
setup_tracing(app, service_name="ml-service")
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "ml"}


@app.get("/ready")
async def ready() -> dict:
    checks = {
        "database": check_database(engine),
        "redis": await check_redis(get_redis),
        "ml_enabled": settings.ML_ENABLED,
    }
    return build_readiness_response(checks)


@app.post("/train")
async def train_models() -> dict:
    if not settings.ML_ENABLED:
        raise HTTPException(status_code=503, detail="Prediction service is disabled")
    return await _run_training()


@app.post("/score")
async def score_models() -> dict:
    if not settings.ML_ENABLED:
        raise HTTPException(status_code=503, detail="Prediction service is disabled")
    return await _run_scoring()


@app.post("/run-cycle")
async def run_cycle() -> dict:
    if not settings.ML_ENABLED:
        raise HTTPException(status_code=503, detail="Prediction service is disabled")
    train_result = await _run_training()
    score_result = await _run_scoring()
    return {"train": train_result, "score": score_result}


@app.get("/status")
def status() -> dict:
    with Session(engine) as session:
        models = session.exec(
            select(MLModelRegistry).where(MLModelRegistry.status == "active").order_by(MLModelRegistry.model_family)
        ).all()
    return {
        "active_models": [
            {
                "model_family": row.model_family,
                "version": row.version,
                "trained_at": row.trained_at.isoformat(),
                "activated_at": row.activated_at.isoformat() if row.activated_at else None,
            }
            for row in models
        ]
    }
