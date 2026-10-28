"""Consumption-rate model: how many percent of a cartridge a printer uses per day.

Two levels, combined by evidence:

* the printer's own rate on its current cartridge (Theil-Sen over the days it
  has been in), which is what actually differs between a busy store and a
  quiet one;
* a prior pooled over every printer using the same cartridge model (falling
  back to the colour, then to defaults) for a cartridge that has just gone in
  and has no history of its own yet.

The printer's own rate gets weight n / (n + K), n = days of history on this
cartridge - after a week it counts as much as the fleet, after a month it
dominates. Days left = level / rate, with a band from the spread of the
pairwise slopes, so a forecast says "9-14 days" when that is all the data
supports instead of a falsely exact number.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass

from .robust import theil_sen
from .series import Segment, normalize_model

ALGORITHM = "theil-sen-shrinkage-v1"

#: Days of own history at which the printer's rate and the prior weigh the same
PRIOR_STRENGTH_DAYS = 7.0
#: Less than this between first and last reading tells nothing about a rate
MIN_SPAN_DAYS = 2.0
#: A cartridge falling faster than this is a misread, not printing (whole
#: cartridge in under ~3 days); slower than the floor is effectively idle.
MAX_RATE = 35.0
MIN_RATE = 0.05
#: Cap on a forecast: beyond a year the number means "not soon", not a date.
MAX_DAYS = 365.0

DEFAULT_COLOR_RATES = {"black": 1.2, "cyan": 0.7, "magenta": 0.7, "yellow": 0.7}


@dataclass(frozen=True)
class RateEstimate:
    rate: float  # % per day
    rate_low: float
    rate_high: float
    span_days: float


@dataclass(frozen=True)
class TonerForecast:
    days: float
    days_low: float
    days_high: float
    daily_rate: float
    basis: str  # printer | cartridge_model | color | default
    confidence: float


def estimate_rate(segment: Segment | None, *, until: float | None = None) -> RateEstimate | None:
    """The segment's consumption rate from its points (up to `until`, if given)."""
    if segment is None:
        return None
    points = [p for p in segment.points if until is None or p[0] <= until]
    if len(points) < 2 or points[-1][0] - points[0][0] < MIN_SPAN_DAYS:
        return None
    fit = theil_sen(points)
    if fit is None:
        return None
    rate = -fit.slope
    if not (MIN_RATE <= rate <= MAX_RATE):
        return None
    return RateEstimate(
        rate=rate,
        # A steeper slope (more negative) is a faster rate
        rate_low=max(-fit.slope_high, MIN_RATE),
        rate_high=min(max(-fit.slope_low, rate), MAX_RATE),
        span_days=points[-1][0] - points[0][0],
    )


def segment_rates(labelled: list[tuple[str, Segment]]) -> list[tuple[str, str, float]]:
    """(colour, normalised cartridge model, rate) for every segment with a usable fit."""
    out: list[tuple[str, str, float]] = []
    for color, segment in labelled:
        est = estimate_rate(segment)
        if est is not None:
            out.append((color, normalize_model(segment.toner_model), est.rate))
    return out


@dataclass
class PooledRate:
    rate: float
    rate_low: float
    rate_high: float
    samples: int


def _pool(rates: list[float]) -> PooledRate:
    ordered = sorted(rates)
    if len(ordered) >= 4:
        q = statistics.quantiles(ordered, n=4)
        low, high = q[0], q[2]
    else:
        low, high = ordered[0], ordered[-1]
    return PooledRate(rate=statistics.median(ordered), rate_low=low, rate_high=high, samples=len(ordered))


class TonerRateModel:
    def __init__(
        self,
        by_model: dict[str, PooledRate] | None = None,
        by_color: dict[str, PooledRate] | None = None,
    ) -> None:
        self.by_model = by_model or {}
        self.by_color = by_color or {}

    # -- training --------------------------------------------------------------

    @classmethod
    def fit(cls, labelled: list[tuple[str, Segment]]) -> TonerRateModel:
        """Pool per-cartridge rates from every (colour, segment) with a usable fit."""
        return cls.from_rates(segment_rates(labelled))

    @classmethod
    def from_rates(cls, rates: list[tuple[str, str, float]]) -> TonerRateModel:
        """Pool already-estimated (colour, cartridge model, rate) triples."""
        by_model: dict[str, list[float]] = {}
        by_color: dict[str, list[float]] = {}
        for color, model_key, rate in rates:
            by_color.setdefault(color, []).append(rate)
            if model_key:
                by_model.setdefault(f"{color}:{model_key}", []).append(rate)
        return cls(
            by_model={k: _pool(v) for k, v in by_model.items()},
            by_color={k: _pool(v) for k, v in by_color.items()},
        )

    # -- prediction ------------------------------------------------------------

    def prior(self, color: str, toner_model: str | None) -> tuple[PooledRate, str]:
        key = f"{color}:{normalize_model(toner_model)}"
        if key in self.by_model:
            return self.by_model[key], "cartridge_model"
        if color in self.by_color:
            return self.by_color[color], "color"
        default = DEFAULT_COLOR_RATES.get(color, 1.0)
        return PooledRate(default, default * 0.5, default * 2.0, 0), "default"

    def forecast(
        self, *, color: str, toner_model: str | None, level: float, own: RateEstimate | None
    ) -> TonerForecast | None:
        if level < 0:
            return None  # "some toner, amount unknown" is not a level to divide
        prior, prior_basis = self.prior(color, toner_model)
        if own is None:
            rate, rate_low, rate_high, basis, weight = prior.rate, prior.rate_low, prior.rate_high, prior_basis, 0.0
        else:
            weight = own.span_days / (own.span_days + PRIOR_STRENGTH_DAYS)
            rate = weight * own.rate + (1 - weight) * prior.rate
            rate_low = weight * own.rate_low + (1 - weight) * prior.rate_low
            rate_high = weight * own.rate_high + (1 - weight) * prior.rate_high
            basis = "printer" if weight >= 0.5 else prior_basis
        rate = max(rate, MIN_RATE)
        rate_low = min(max(rate_low, MIN_RATE), rate)
        rate_high = max(rate_high, rate)
        days = min(level / rate, MAX_DAYS)
        days_low = min(level / rate_high, days)
        days_high = min(level / rate_low, MAX_DAYS)
        # How tight the band is relative to the estimate, nudged up by how much
        # of it is this printer's own history rather than the fleet's.
        spread = (days_high - days_low) / max(days, 1.0)
        confidence = max(0.05, min(0.95, (1.0 / (1.0 + spread)) * (0.6 + 0.4 * weight)))
        return TonerForecast(
            days=days,
            days_low=days_low,
            days_high=days_high,
            daily_rate=rate,
            basis=basis,
            confidence=round(confidence, 3),
        )

    # -- persistence -----------------------------------------------------------

    def to_metadata(self) -> dict:
        return {
            "algorithm": ALGORITHM,
            "by_model": {k: asdict(v) for k, v in self.by_model.items()},
            "by_color": {k: asdict(v) for k, v in self.by_color.items()},
        }

    @classmethod
    def from_metadata(cls, payload: dict) -> TonerRateModel | None:
        if payload.get("algorithm") != ALGORITHM:
            return None
        return cls(
            by_model={k: PooledRate(**v) for k, v in payload.get("by_model", {}).items()},
            by_color={k: PooledRate(**v) for k, v in payload.get("by_color", {}).items()},
        )
