"""A right-sized thread pool behind asyncio.to_thread.

asyncio's default executor has min(32, cpu + 4) threads - 8 on the 4-vCPU
production server. Everything that still blocks on the network (paramiko SSH
to switches, the sync SNMP switch provider, ping/ARP subprocesses, HTTP toner
scraping) runs there, so any poll built on to_thread was capped at 8 devices at
a time no matter what its own concurrency setting said. These threads spend
their life waiting on sockets, not on the CPU, so a few dozen cost nothing.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from app.core.config import settings


def install_io_executor(loop: asyncio.AbstractEventLoop | None = None) -> ThreadPoolExecutor:
    """Give `loop` (default: the running one) a BLOCKING_IO_THREADS-wide pool.

    asyncio.run() shuts the default executor down with the loop, so a Celery
    task's pool goes away with its loop; the API keeps its for the process.
    """
    loop = loop or asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=max(8, settings.BLOCKING_IO_THREADS), thread_name_prefix="blocking-io")
    loop.set_default_executor(executor)
    return executor
