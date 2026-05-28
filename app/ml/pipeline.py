from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, delete, select

from app.domains.inventory.models import Printer
from app.domains.ml.models import MLFeatureSnapshot, MLModelRegistry, MLOfflineRiskPrediction, MLTonerPrediction
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

_DEFAULT_COLOR_RATES = {
    "black": 1.2,
    "cyan": 0.7,
    "magenta": 0.7,
    "yellow": 0.7,
}


def _clamp01(value: float) -> float:
    return max(0.0, min(value, 1.0))


def _new_version(prefix: str) -> str:
    return f"{prefix}-{datetime.now(UTC):%Y%m%d%H%M%S}"


def _latest_active_model(session: Session, family: str) -> MLModelRegistry | None:
    return session.exec(
        select(MLModelRegistry)
        .where(MLModelRegistry.model_family == family, MLModelRegistry.status == _ACTIVE)
        .order_by(MLModelRegistry.activated_at.desc(), MLModelRegistry.trained_at.desc())
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


def train_toner_model(session: Session, min_train_rows: int = 50) -> MLModelRegistry:
    with ml_train_duration_seconds.labels(model_family=_TONER_FAMILY).time():
        samples = session.exec(
            select(MLFeatureSnapshot)
            .where(
                MLFeatureSnapshot.device_kind == "printer",
                MLFeatureSnapshot.toner_color.is_not(None),
                MLFeatureSnapshot.toner_level.is_not(None),
            )
            .order_by(
                MLFeatureSnapshot.device_id,
                MLFeatureSnapshot.toner_color,
                MLFeatureSnapshot.captured_at,
            )
        ).all()

        grouped: dict[tuple[str, str], list[MLFeatureSnapshot]] = defaultdict(list)
        for row in samples:
            if row.device_id is None or row.toner_color is None or row.toner_level is None:
                continue
            grouped[(str(row.device_id), row.toner_color)].append(row)

        rates_by_key: dict[str, list[float]] = defaultdict(list)
        rates_by_color: dict[str, list[float]] = defaultdict(list)
        all_rates: list[float] = []
        abs_errors: list[float] = []

        for (_device, color), rows in grouped.items():
            for idx in range(1, len(rows)):
                prev = rows[idx - 1]
                cur = rows[idx]
                if prev.toner_level is None or cur.toner_level is None:
                    continue
                delta = prev.toner_level - cur.toner_level
                days = max((cur.captured_at - prev.captured_at).total_seconds() / 86400.0, 0)
                if delta <= 0 or days <= 0:
                    continue
                rate = delta / days
                key = f"{color}:{(cur.toner_model or '').strip().lower() or 'unknown'}"
                rates_by_key[key].append(rate)
                rates_by_color[color].append(rate)
                all_rates.append(rate)

        key_model = {k: statistics.median(v) for k, v in rates_by_key.items() if v}
        color_model = {k: statistics.median(v) for k, v in rates_by_color.items() if v}
        global_rate = statistics.median(all_rates) if all_rates else 1.0

        for rates in rates_by_key.values():
            med = statistics.median(rates)
            abs_errors.extend(abs(v - med) for v in rates)
        mae = statistics.mean(abs_errors) if abs_errors else None

        model = MLModelRegistry(
            model_family=_TONER_FAMILY,
            version=_new_version("toner"),
            status="candidate",
            train_rows=len(all_rates),
            metric_primary=mae,
            metric_secondary=statistics.mean(all_rates) if all_rates else 0.0,
            metadata_json=json.dumps(
                {
                    "rates_by_key": key_model,
                    "rates_by_color": color_model,
                    "global_daily_rate": global_rate,
                    "default_color_rates": _DEFAULT_COLOR_RATES,
                },
                ensure_ascii=True,
            ),
        )
        session.add(model)

        active = _latest_active_model(session, _TONER_FAMILY)
        can_activate = len(all_rates) >= min_train_rows
        if active and active.metric_primary is not None and model.metric_primary is not None:
            can_activate = can_activate and (model.metric_primary <= active.metric_primary * 1.05)
        if active is None and len(all_rates) > 0:
            can_activate = True
        if can_activate:
            _set_active_model(session, model)
            ml_train_runs_total.labels(model_family=_TONER_FAMILY, result="activated").inc()
        else:
            ml_train_runs_total.labels(model_family=_TONER_FAMILY, result="candidate").inc()
        return model


def train_offline_risk_model(session: Session, min_train_rows: int = 50) -> MLModelRegistry:
    with ml_train_duration_seconds.labels(model_family=_OFFLINE_FAMILY).time():
        rows = session.exec(
            select(MLFeatureSnapshot)
            .where(MLFeatureSnapshot.is_online.is_not(None))
            .order_by(MLFeatureSnapshot.device_kind, MLFeatureSnapshot.device_id, MLFeatureSnapshot.captured_at)
        ).all()

        grouped: dict[tuple[str, str], list[MLFeatureSnapshot]] = defaultdict(list)
        for row in rows:
            if row.device_id is None:
                continue
            grouped[(row.device_kind, str(row.device_id))].append(row)

        device_features: list[tuple[float, float, float]] = []
        for _key, items in grouped.items():
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
    with ml_inference_duration_seconds.labels(operation="toner").time():
        model = _latest_active_model(session, _TONER_FAMILY)
        if not model or not model.metadata_json:
            return 0
        payload = json.loads(model.metadata_json)
        rates_by_key: dict[str, float] = payload.get("rates_by_key", {})
        rates_by_color: dict[str, float] = payload.get("rates_by_color", {})
        default_rates: dict[str, float] = payload.get("default_color_rates", _DEFAULT_COLOR_RATES)
        global_rate: float = float(payload.get("global_daily_rate", 1.0))
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
                key = f"{color}:{(toner_model or '').strip().lower() or 'unknown'}"
                rate = (
                    rates_by_key.get(key) or rates_by_color.get(color) or default_rates.get(color) or global_rate or 1.0
                )
                if rate <= 0:
                    continue
                days = max(float(level) / float(rate), 0.0)
                confidence = 0.92 if key in rates_by_key else (0.78 if color in rates_by_color else 0.6)
                session.add(
                    MLTonerPrediction(
                        printer_id=printer.id,
                        printer_name=printer.store_name,
                        toner_color=color,
                        toner_model=toner_model,
                        current_level=level,
                        days_to_replacement=days,
                        predicted_replacement_at=now + timedelta(days=days),
                        confidence=confidence,
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
                MLFeatureSnapshot.is_online.is_not(None),
                MLFeatureSnapshot.captured_at >= since,
            )
            .order_by(MLFeatureSnapshot.device_kind, MLFeatureSnapshot.device_id, MLFeatureSnapshot.captured_at)
        ).all()
        grouped: dict[tuple[str, str], list[MLFeatureSnapshot]] = defaultdict(list)
        for row in rows:
            if row.device_id is None:
                continue
            grouped[(row.device_kind, str(row.device_id))].append(row)

        created = 0
        risk_counts: dict[str, int] = {"low": 0, "medium": 0, "high": 0}
        for (_kind, _id), items in grouped.items():
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
    toner_count = score_toner_predictions(session)
    risk_count = score_offline_risk(session)
    session.commit()
    return {"toner_predictions": toner_count, "offline_risk_predictions": risk_count}
