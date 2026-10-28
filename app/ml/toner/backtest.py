"""Out-of-sample check: would the model have called finished cartridges right?

For every cartridge life that ran its course (it was replaced, or it reached a
near-empty level), stand at 30, 14 and 7 days before its last reading, fit
using only what was known then - the printer's own points up to that day, and
a prior pooled from *other* printers - and forecast when the cartridge would
reach the level it actually ended at. The error is in days, which is what a
person ordering cartridges cares about.

This replaces the old "MAE", which measured how far each training rate sat
from the median of the same training rates - a number that improves when the
model gets worse at forecasting, and which gated model activation.
"""

from __future__ import annotations

import statistics
import uuid
from dataclasses import dataclass

from .model import TonerRateModel, estimate_rate
from .series import Segment, normalize_model

HORIZONS_DAYS = (30, 14, 7)
#: A cartridge life must cover this much to be worth checking a forecast on
MIN_SEGMENT_DAYS = 10.0
MIN_SEGMENT_DROP = 20.0
#: Needs this much own history before the cut to be a fair forecast
MIN_DAYS_BEFORE_CUT = 3.0
NEAR_EMPTY_LEVEL = 5.0


@dataclass(frozen=True)
class BacktestResult:
    cases: int
    mae_days: float | None
    by_horizon: dict[int, float]


def _finished(segment: Segment) -> bool:
    return (segment.ended_by_refill or segment.last_level <= NEAR_EMPTY_LEVEL) and (
        segment.span_days >= MIN_SEGMENT_DAYS and segment.first_level - segment.last_level >= MIN_SEGMENT_DROP
    )


def backtest(labelled: list[tuple[uuid.UUID, str, Segment]]) -> BacktestResult:
    errors: dict[int, list[float]] = {h: [] for h in HORIZONS_DAYS}
    # Each segment's rate once, not once per finished cartridge being checked
    rated: list[tuple[uuid.UUID, str, str, float]] = []
    for printer_id, color, segment in labelled:
        est = estimate_rate(segment)
        if est is not None:
            rated.append((printer_id, color, normalize_model(segment.toner_model), est.rate))
    for printer_id, color, segment in labelled:
        if not _finished(segment):
            continue
        # Prior from everyone else: the printer's own history must not leak
        # into the pooled rate it is being compared against.
        model = TonerRateModel.from_rates([(c, m, r) for p, c, m, r in rated if p != printer_id])
        start, end = segment.points[0][0], segment.points[-1][0]
        for horizon in HORIZONS_DAYS:
            cut = end - horizon
            if cut - start < MIN_DAYS_BEFORE_CUT:
                continue
            known = [p for p in segment.points if p[0] <= cut]
            level_at_cut = known[-1][1]
            remaining = level_at_cut - segment.last_level
            if remaining <= 0:
                continue
            forecast = model.forecast(
                color=color,
                toner_model=segment.toner_model,
                level=remaining,
                own=estimate_rate(segment, until=cut),
            )
            if forecast is None:
                continue
            errors[horizon].append(abs(forecast.days - (end - known[-1][0])))
    all_errors = [e for es in errors.values() for e in es]
    return BacktestResult(
        cases=len(all_errors),
        mae_days=statistics.mean(all_errors) if all_errors else None,
        by_horizon={h: statistics.mean(es) for h, es in errors.items() if es},
    )
