from __future__ import annotations

import asyncio
import time

import pytest

from app.observability import loop_lag


def _sum(service: str) -> float:
    return loop_lag.event_loop_lag_seconds.labels(service=service)._sum.get()


@pytest.mark.asyncio
async def test_a_blocked_loop_shows_up_as_lag(monkeypatch) -> None:
    monkeypatch.setattr(loop_lag, "_INTERVAL_SECONDS", 0.02)
    before = _sum("blocked")
    task = loop_lag.start_loop_lag_monitor("blocked")

    await asyncio.sleep(0.05)  # let the sampler start a sleep
    time.sleep(0.3)  # what a sync DB call inside an async handler does
    await asyncio.sleep(0.05)
    await loop_lag.stop_loop_lag_monitor(task)

    assert _sum("blocked") - before >= 0.2


@pytest.mark.asyncio
async def test_an_idle_loop_reports_almost_nothing(monkeypatch) -> None:
    monkeypatch.setattr(loop_lag, "_INTERVAL_SECONDS", 0.02)
    before = _sum("idle")
    task = loop_lag.start_loop_lag_monitor("idle")

    await asyncio.sleep(0.2)
    await loop_lag.stop_loop_lag_monitor(task)

    assert _sum("idle") - before < 0.1


@pytest.mark.asyncio
async def test_stopping_the_monitor_ends_the_task() -> None:
    task = loop_lag.start_loop_lag_monitor("stop")
    await loop_lag.stop_loop_lag_monitor(task)

    assert task.done() and task.cancelled()
