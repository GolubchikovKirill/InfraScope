from __future__ import annotations

import asyncio
import threading
import time

from app.core import io_pool


def test_to_thread_is_no_longer_capped_at_the_default_eight(monkeypatch) -> None:
    monkeypatch.setattr(io_pool.settings, "BLOCKING_IO_THREADS", 32)
    peak = 0
    current = 0
    lock = threading.Lock()

    def _blocking():
        nonlocal peak, current
        with lock:
            current += 1
            peak = max(peak, current)
        time.sleep(0.2)
        with lock:
            current -= 1

    async def _main():
        io_pool.install_io_executor()
        await asyncio.gather(*(asyncio.to_thread(_blocking) for _ in range(24)))

    asyncio.run(_main())

    assert peak == 24
