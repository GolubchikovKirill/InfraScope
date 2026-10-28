from __future__ import annotations

import json
import statistics
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, col, delete, select

from app.core.config import settings
from app.domains.inventory.models import Printer
from app.domains.ml.models import MLFeatureSnapshot, MLModelRegistry, MLOfflineRiskPrediction, MLTonerPrediction
from app.ml.toner import ALGORITHM as TONER_ALGORITHM
from app.ml.toner import (
    Segment,
    TonerRateModel,
    backtest,
    estimate_rate,
    load_daily_readings,
    segment_rates,
    split_segments,
)
from app.observability.metrics import (
    ml_inference_duration_seconds,
    ml_model_active_info,
    ml_predictions_total,
    ml_train_duration_seconds,
    ml_train_runs_total,
)

_TONER_FAMILY = "toner_forecast"
_OFFLINE_FAMILY = "offline_risk"
_ACTIVE = "active"
_ARCHIVED = "archived"

def _clamp01(value: float) -> float:
    return max(0.0, min(value, 1.0))


def _new_version(prefix: str) -> str:
    return f"{prefix}-{datetime.now(UTC):%Y%m%d%H%M%S}"


def _latest_active_model(session: Session, family: str) -> MLModelRegistry | None:
    return session.exec(
        select(MLModelRegistry)
        .where(MLModelRegistry.model_family == family, MLModelRegistry.status == _ACTIVE)
        .order_by(col(MLModelRegistry.activated_at).desc(), col(MLModelRegistry.trained_at).desc())
    ).first()


def _set_active_model(session: Session, model: MLModelRegistry) -> None:
    active = session.exec(
        select(MLModelRegistry).where(
            MLModelRegistry.model_family == model.model_family,
            MLModelRegistry.status == _ACTIVE,
        )
    ).all()
    for row in active:
        row.status = _ARCHIVED
        session.add(row)
    model.status = _ACTIVE
    model.activated_at = datetime.now(UTC)
    session.add(model)
    ml_model_active_info.labels(model_family=model.model_family, version=model.version).set(1)


def _toner_history_window() -> datetime:
    # Bounded to the window app.ml.retention keeps raw snapshots for: a rate
    # drifts with how a store uses its printer, so recent cartridges are the
    # representative ones, and the query stays bounded whether or not the
    # daily prune has run yet.
    return datetime.now(UTC) - timedelta(days=max(settings.ML_FEATURE_SNAPSHOT_RETENTION_DAYS, 1))


def _toner_segments(session: Session) -> list[tuple[uuid.UUID, str, Segment]]:
    labelled: list[tuple[uuid.UUID, str, Segment]] = []
    for (printer_id, color), readings in load_daily_readings(session, _toner_history_window()).items():
        labelled.extend((printer_id, color, segment) for segment in split_segments(readings))
    return labelled


def train_toner_model(session: Session, min_train_rows: int = 50) -> MLModelRegistry:
    """Fit the fleet prior and score it on finished cartridges (see app.ml.toner).

    train_rows counts cartridge lifetimes with a usable rate; metric_primary is
    the backtest error in days (lower is better), metric_secondary the median
    consumption in % per day.
    """
    with ml_train_duration_seconds.labels(model_family=_TONER_FAMILY).time():
        labelled = _toner_segments(session)
        rates = segment_rates([(color, segment) for _printer, color, segment in labelled])
        rate_model = TonerRateModel.from_rates(rates)
        check = backtest(labelled)

        metadata = rate_model.to_metadata()
        metadata["backtest"] = {
            "cases": check.cases,
            "mae_days": check.mae_days,
            "mae_days_by_horizon": check.by_horizon,
        }
        model = MLModelRegistry(
            model_family=_TONER_FAMILY,
            version=_new_version("toner"),
            status="candidate",
            train_rows=len(rates),
            metric_primary=check.mae_days,
            metric_secondary=statistics.median(r for _c, _m, r in rates) if rates else 0.0,
            metadata_json=json.dumps(metadata, ensure_ascii=True),
        )
        session.add(model)

        active = _latest_active_model(session, _TONER_FAMILY)
        if active is None or not _same_toner_algorithm(active):
            # Nothing to compare against - including the pre-v1 model, whose
            # "error" measured something else entirely and whose forecasts
            # were wrong by two orders of magnitude.
            can_activate = len(rates) > 0
        else:
            can_activate = len(rates) >= min_train_rows
            if active.metric_primary is not None and model.metric_primary is not None:
                can_activate = can_activate and model.metric_primary <= active.metric_primary * 1.05
        if can_activate:
            _set_active_model(session, model)
            ml_train_runs_total.labels(model_family=_TONER_FAMILY, result="activated").inc()
        else:
            ml_train_runs_total.labels(model_family=_TONER_FAMILY, result="candidate").inc()
        return model


def _same_toner_algorithm(model: MLModelRegistry) -> bool:
    try:
        return json.loads(model.metadata_json or "{}").get("algorithm") == TONER_ALGORITHM
    except ValueError:
        return False


def train_offline_risk_model(session: Session, min_train_rows: int = 50) -> MLModelRegistry:
    with ml_train_duration_seconds.labels(model_family=_OFFLINE_FAMILY).time():
        # Same bounded window as train_toner_model above, same reasoning.
        since = datetime.now(UTC) - timedelta(days=max(settings.ML_FEATURE_SNAPSHOT_RETENTION_DAYS, 1))
        rows = session.exec(
            select(MLFeatureSnapshot)
            .where(col(MLFeatureSnapshot.is_online).is_not(None), MLFeatureSnapshot.captured_at >= since)
            .order_by(
                col(MLFeatureSnapshot.device_kind), col(MLFeatureSnapshot.device_id), col(MLFeatureSnapshot.captured_at)
            )
        ).all()

        grouped: dict[tuple[str, str], list[MLFeatureSnapshot]] = defaultdict(list)
        for row in rows:
            if row.device_id is None:
                continue
            grouped[(row.device_kind, str(row.device_id))].append(row)

        device_features: list[tuple[float, float, float]] = []
        for items in grouped.values():
            if len(items) < 2:
                continue
            offline_count = sum(1 for item in items if item.is_online is False)
            offline_ratio = offline_count / len(items)
            flaps = 0
            for idx in range(1, len(items)):
                if items[idx - 1].is_online != items[idx].is_online:
                    flaps += 1
            flap_rate = flaps / max(len(items) - 1, 1)
            label = offline_ratio
            device_features.append((offline_ratio, flap_rate, label))

        if device_features:
            mean_offline = statistics.mean(x[0] for x in device_features)
            mean_flap = statistics.mean(x[1] for x in device_features)
            total = max(mean_offline + mean_flap, 1e-6)
            w_offline = mean_offline / total
            w_flap = mean_flap / total
        else:
            w_offline, w_flap = 0.7, 0.3

        errors: list[float] = []
        for offline_ratio, flap_rate, label in device_features:
            pred = _clamp01((offline_ratio * w_offline) + (flap_rate * w_flap))
            errors.append(abs(label - pred))
        mae = statistics.mean(errors) if errors else None

        model = MLModelRegistry(
            model_family=_OFFLINE_FAMILY,
            version=_new_version("offline"),
            status="candidate",
            train_rows=len(device_features),
            metric_primary=mae,
            metric_secondary=statistics.mean(x[0] for x in device_features) if device_features else 0.0,
            metadata_json=json.dumps({"w_offline": w_offline, "w_flap": w_flap}, ensure_ascii=True),
        )
        session.add(model)

        active = _latest_active_model(session, _OFFLINE_FAMILY)
        can_activate = len(device_features) >= min_train_rows
        if active and active.metric_primary is not None and model.metric_primary is not None:
            can_activate = can_activate and (model.metric_primary <= active.metric_primary * 1.05)
        if active is None and len(device_features) > 0:
            can_activate = True
        if can_activate:
            _set_active_model(session, model)
            ml_train_runs_total.labels(model_family=_OFFLINE_FAMILY, result="activated").inc()
        else:
            ml_train_runs_total.labels(model_family=_OFFLINE_FAMILY, result="candidate").inc()
        return model


def score_toner_predictions(session: Session) -> int:
    """Days until each printer's cartridges run out, with a band.

    The printer's own rate on its current cartridge is re-estimated here from
    fresh data (the daily aggregate is cheap), so a forecast reacts within the
    day; only the fleet prior comes from the trained model.
    """
    with ml_inference_duration_seconds.labels(operation="toner").time():
        model = _latest_active_model(session, _TONER_FAMILY)
        if not model or not model.metadata_json:
            return 0
        rate_model = TonerRateModel.from_metadata(json.loads(model.metadata_json))
        if rate_model is None:
            # An old-format model: no forecasts until the next training run
            # replaces it, rather than publishing its broken numbers again.
            return 0
        current_segment: dict[tuple[uuid.UUID, str], Segment] = {}
        for (printer_id, color), readings in load_daily_readings(session, _toner_history_window()).items():
            segments = split_segments(readings)
            if segments:
                current_segment[(printer_id, color)] = segments[-1]
        now = datetime.now(UTC)

        # Keep a fresh prediction snapshot to avoid unbounded table growth.
        session.exec(delete(MLTonerPrediction))
        printers = session.exec(select(Printer)).all()
        created = 0
        for printer in printers:
            for color, level, toner_model in (
                ("black", printer.toner_black, printer.toner_black_name),
                ("cyan", printer.toner_cyan, printer.toner_cyan_name),
                ("magenta", printer.toner_magenta, printer.toner_magenta_name),
                ("yellow", printer.toner_yellow, printer.toner_yellow_name),
            ):
                if level is None:
                    continue
                forecast = rate_model.forecast(
                    color=color,
                    toner_model=toner_model,
                    level=float(level),
                    own=estimate_rate(current_segment.get((printer.id, color))),
                )
                if forecast is None:
                    continue  # -2/-3: the printer does not say how much is left
                session.add(
                    MLTonerPrediction(
                        printer_id=printer.id,
                        printer_name=printer.store_name,
                        toner_color=color,
                        toner_model=toner_model,
                        current_level=level,
                        days_to_replacement=forecast.days,
                        days_low=forecast.days_low,
                        days_high=forecast.days_high,
                        daily_rate=forecast.daily_rate,
                        basis=forecast.basis,
                        predicted_replacement_at=now + timedelta(days=forecast.days),
                        confidence=forecast.confidence,
                        model_version=model.version,
                    )
                )
                created += 1
        ml_predictions_total.labels(prediction_kind="toner", risk_level="n/a").inc(created)
        return created


def _risk_level(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def score_offline_risk(session: Session) -> int:
    with ml_inference_duration_seconds.labels(operation="offline_risk").time():
        model = _latest_active_model(session, _OFFLINE_FAMILY)
        if not model or not model.metadata_json:
            return 0
        payload = json.loads(model.metadata_json)
        w_offline = float(payload.get("w_offline", 0.7))
        w_flap = float(payload.get("w_flap", 0.3))
        since = datetime.now(UTC) - timedelta(days=7)
        # Keep a fresh prediction snapshot to avoid unbounded table growth.
        session.exec(delete(MLOfflineRiskPrediction))
        rows = session.exec(
            select(MLFeatureSnapshot)
            .where(
                col(MLFeatureSnapshot.is_online).is_not(None),
                MLFeatureSnapshot.captured_at >= since,
            )
            .order_by(
                col(MLFeatureSnapshot.device_kind), col(MLFeatureSnapshot.device_id), col(MLFeatureSnapshot.captured_at)
            )
        ).all()
        grouped: dict[tuple[str, str], list[MLFeatureSnapshot]] = defaultdict(list)
        for row in rows:
            if row.device_id is None:
                continue
            grouped[(row.device_kind, str(row.device_id))].append(row)

        created = 0
        risk_counts: dict[str, int] = {"low": 0, "medium": 0, "high": 0}
        for items in grouped.values():
            if len(items) < 2:
                continue
            offline_ratio = sum(1 for i in items if i.is_online is False) / len(items)
            flaps = sum(1 for idx in range(1, len(items)) if items[idx - 1].is_online != items[idx].is_online)
            flap_rate = flaps / max(len(items) - 1, 1)
            score = _clamp01((offline_ratio * w_offline) + (flap_rate * w_flap))
            level = _risk_level(score)
            latest = items[-1]
            confidence = min(0.95, 0.5 + (len(items) / 80))
            session.add(
                MLOfflineRiskPrediction(
                    device_kind=latest.device_kind,
                    device_id=latest.device_id,
                    device_name=latest.device_name,
                    address=latest.address,
                    risk_score=score,
                    risk_level=level,
                    confidence=confidence,
                    model_version=model.version,
                )
            )
            risk_counts[level] = risk_counts.get(level, 0) + 1
            created += 1
        for level, count in risk_counts.items():
            if count > 0:
                ml_predictions_total.labels(prediction_kind="offline_risk", risk_level=level).inc(count)
        return created


def run_training_cycle(session: Session, min_train_rows: int = 50) -> dict[str, str]:
    toner = train_toner_model(session, min_train_rows=min_train_rows)
    offline = train_offline_risk_model(session, min_train_rows=min_train_rows)
    session.commit()
    return {"toner_model_version": toner.version, "offline_model_version": offline.version}


def run_scoring_cycle(session: Session) -> dict[str, int]:
    active = _latest_active_model(session, _TONER_FAMILY)
    if active is not None and not _same_toner_algorithm(active):
        # First scoring after an upgrade: the nightly retrain is up to a day
        # away, and the old model's forecasts are the ones being replaced.
        train_toner_model(session, min_train_rows=settings.ML_MIN_TRAIN_ROWS)
        session.flush()
    toner_count = score_toner_predictions(session)
    risk_count = score_offline_risk(session)
    session.commit()
    return {"toner_predictions": toner_count, "offline_risk_predictions": risk_count}
