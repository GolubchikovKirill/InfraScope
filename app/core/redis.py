"""Redis connection pool for caching, sessions, and scan results."""

from __future__ import annotations

import asyncio
import weakref

import redis.asyncio as aioredis

from app.core.config import settings

# One pool per running event loop, not one per process.
#
# An asyncio Redis connection is bound to the loop that opened it. The API and
# the *-service processes have a single long-lived loop, so a module-global pool
# was fine there. Celery tasks are different: each one does asyncio.run(...),
# i.e. a fresh loop that is closed when the task ends, while the global pool
# (and its idle connections) lived on. The next task then reused a connection
# from a closed loop and failed with "RuntimeError: Event loop is closed" -
# measured on the production worker: every second asyncio.run() failed. Callers
# such as poll_resilience swallow Redis errors on purpose, so the symptom was
# not an error but the offline-confirmation grace period and the circuit
# breaker silently switching themselves off.
#
# Keyed weakly by loop so a closed loop's entry can be collected.
_pools: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, aioredis.Redis] = weakref.WeakKeyDictionary()


async def get_redis() -> aioredis.Redis:
    loop = asyncio.get_running_loop()
    pool = _pools.get(loop)
    if pool is None:
        pool = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
        )
        _pools[loop] = pool
    return pool


async def close_redis() -> None:
    """Close the pool of the *current* loop. A task that owns its loop (see
    run_async in app.worker.tasks) must call this before the loop goes away."""
    pool = _pools.pop(asyncio.get_running_loop(), None)
    if pool is not None:
        await pool.aclose()
