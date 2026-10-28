"""Toner level history, shaped for fitting: one point per printer, colour and day,
split into cartridge lifetimes.

Why not the raw snapshots: a printer is snapshotted every 15 minutes but its
toner is re-read once an hour and reported in whole percent, so almost every
consecutive pair is flat and the rare 1 % step lands in a 15-minute gap. A rate
taken pair by pair reads that as ~96 %/day for a printer using 1 %/day - which
is exactly how the previous model forecast "replace today" for everyone. One
point per day keeps the signal and drops the quantisation artefacts, and the
aggregation runs in SQL: ~20 thousand rows reach Python instead of ~2 million.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy import select as sa_select
from sqlmodel import Session, col

from app.domains.ml.models import MLFeatureSnapshot

#: A rise this large between days is a cartridge swap, not measurement noise.
REFILL_JUMP = 15


@dataclass(frozen=True)
class DailyReading:
    day: date
    low: int  # lowest level seen that day
    high: int  # highest level seen that day - differs from low on a swap day
    toner_model: str | None


@dataclass
class Segment:
    """One cartridge's life: (day number, level) points while it was installed."""

    points: list[tuple[float, float]] = field(default_factory=list)
    toner_model: str | None = None
    ended_by_refill: bool = False

    @property
    def span_days(self) -> float:
        return self.points[-1][0] - self.points[0][0] if len(self.points) > 1 else 0.0

    @property
    def first_level(self) -> float:
        return self.points[0][1]

    @property
    def last_level(self) -> float:
        return self.points[-1][1]


SeriesKey = tuple[uuid.UUID, str]  # (printer id, colour)


def _as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def normalize_model(name: str | None) -> str:
    return (name or "").strip().lower()


def load_daily_readings(session: Session, since: datetime) -> dict[SeriesKey, list[DailyReading]]:
    """Daily min/max toner level per printer and colour, online readings only.

    Offline snapshots are excluded: they carry the last known level forward
    unchanged, and a week of a printer switched off would read as a week of
    zero consumption. Negative levels are the Printer-MIB codes for "some
    toner, unknown amount" (-3) and "unknown" (-2), not levels.
    """
    day = func.date(MLFeatureSnapshot.captured_at)
    # sqlalchemy's select: sqlmodel's typed overloads stop at four columns
    rows = session.execute(
        sa_select(
            col(MLFeatureSnapshot.device_id),
            col(MLFeatureSnapshot.toner_color),
            day,
            func.min(MLFeatureSnapshot.toner_level),
            func.max(MLFeatureSnapshot.toner_level),
            func.max(MLFeatureSnapshot.toner_model),
        )
        .where(
            col(MLFeatureSnapshot.device_kind) == "printer",
            col(MLFeatureSnapshot.device_id).is_not(None),
            col(MLFeatureSnapshot.toner_color).is_not(None),
            col(MLFeatureSnapshot.toner_level).is_not(None),
            col(MLFeatureSnapshot.toner_level) >= 0,
            col(MLFeatureSnapshot.is_online).is_not(False),
            col(MLFeatureSnapshot.captured_at) >= since,
        )
        .group_by(col(MLFeatureSnapshot.device_id), col(MLFeatureSnapshot.toner_color), day)
    ).all()

    series: dict[SeriesKey, list[DailyReading]] = defaultdict(list)
    for device_id, color, raw_day, low, high, toner_model in rows:
        if device_id is None or color is None or low is None or high is None:
            continue
        series[(device_id, color)].append(DailyReading(_as_date(raw_day), int(low), int(high), toner_model))
    for readings in series.values():
        readings.sort(key=lambda r: r.day)
    return dict(series)


def split_segments(readings: list[DailyReading]) -> list[Segment]:
    """Cut a daily series into cartridge lifetimes at every swap.

    On a swap day the low reading belongs to the old cartridge and the high one
    starts the new cartridge. Segments are returned oldest first; only the last
    one can still be in use (`ended_by_refill` False).
    """
    segments: list[Segment] = []
    current = Segment()
    previous_level: int | None = None
    for reading in readings:
        x = float(reading.day.toordinal())
        swapped = previous_level is not None and reading.high >= previous_level + REFILL_JUMP
        if swapped:
            if reading.low < (previous_level or 0):
                current.points.append((x, float(reading.low)))
            current.ended_by_refill = True
            segments.append(current)
            current = Segment(points=[(x, float(reading.high))], toner_model=reading.toner_model)
            previous_level = reading.high
            continue
        current.points.append((x, float(reading.low)))
        current.toner_model = reading.toner_model or current.toner_model
        previous_level = reading.low
    if current.points:
        segments.append(current)
    return segments
