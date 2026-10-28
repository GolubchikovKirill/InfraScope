"""Theil-Sen line fit: the median of all pairwise slopes.

Chosen over least squares because toner readings are steps (whole percent,
some printers only report 10 % steps) with the occasional misread; one bad
point moves a least-squares slope a lot and the median of slopes hardly at
all. The spread of the pairwise slopes doubles as an honest uncertainty band.
O(n^2) pairs, which for one point per day over a cartridge's life is at most a
few thousand.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass


@dataclass(frozen=True)
class SlopeFit:
    slope: float
    slope_low: float  # 20th percentile of pairwise slopes
    slope_high: float  # 80th percentile


def _quantile(sorted_values: list[float], q: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def theil_sen(points: list[tuple[float, float]]) -> SlopeFit | None:
    slopes = sorted(
        (y2 - y1) / (x2 - x1)
        for i, (x1, y1) in enumerate(points)
        for x2, y2 in points[i + 1 :]
        if x2 != x1
    )
    if not slopes:
        return None
    return SlopeFit(
        slope=statistics.median(slopes),
        slope_low=_quantile(slopes, 0.2),
        slope_high=_quantile(slopes, 0.8),
    )
