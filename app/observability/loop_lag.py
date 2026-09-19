"""How long the asyncio event loop is kept from running by blocking code.

A sync DB call or a blocking socket inside an `async def` handler stalls every
other request and websocket on that loop for its whole duration. Nothing measured
that. This samples it: sleep a fixed interval and record how much later than
planned the loop woke us. On a healthy loop the overshoot is ~0; a slow query in
a handler shows up as a spike of that length.
"""

from __future__ import annotations

import asyncio
import contextlib
from time import perf_counter

from prometheus_client import Histogram

_INTERVAL_SECONDS = 0.25

event_loop_lag_seconds = Histogram(
    "infrascope_event_loop_lag_seconds",
    "How much later than scheduled the event loop resumed a timer (time blocked by synchronous code).",
    ["service"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)


async def _sample(service: str) -> None:
    lag = event_loop_lag_seconds.labels(service=service)
    while True:
        started = perf_counter()
        await asyncio.sleep(_INTERVAL_SECONDS)
        lag.observe(max(perf_counter() - started - _INTERVAL_SECONDS, 0.0))


def start_loop_lag_monitor(service: str) -> asyncio.Task[None]:
    """Start sampling on the running loop; cancel the returned task on shutdown."""
    return asyncio.create_task(_sample(service), name=f"loop-lag-{service}")


async def stop_loop_lag_monitor(task: asyncio.Task[None]) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
