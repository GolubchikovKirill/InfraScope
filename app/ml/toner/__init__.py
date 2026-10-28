"""Toner forecasting: daily series -> cartridge lifetimes -> robust per-printer
rates shrunk towards a fleet prior -> days left with a band, validated on
finished cartridges. See the module docstrings for the reasoning."""

from .backtest import BacktestResult, backtest
from .model import ALGORITHM, TonerForecast, TonerRateModel, estimate_rate, segment_rates
from .series import DailyReading, Segment, load_daily_readings, normalize_model, split_segments

__all__ = [
    "ALGORITHM",
    "BacktestResult",
    "DailyReading",
    "Segment",
    "TonerForecast",
    "TonerRateModel",
    "backtest",
    "estimate_rate",
    "load_daily_readings",
    "normalize_model",
    "segment_rates",
    "split_segments",
]
