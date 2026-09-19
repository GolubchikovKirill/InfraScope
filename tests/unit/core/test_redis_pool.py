from __future__ import annotations

import asyncio

from app.core import redis as core_redis
from app.worker import tasks


def test_same_loop_reuses_one_pool():
    async def _twice():
        first = await core_redis.get_redis()
        second = await core_redis.get_redis()
        return first is second

    assert asyncio.run(_twice()) is True


def test_each_event_loop_gets_its_own_pool():
    """A pool is bound to the loop that opened its connections. Handing the
    previous loop's pool to a new asyncio.run() is what produced "Event loop
    is closed" on every second Celery task in production."""
    pools = []

    async def _grab():
        pools.append(await core_redis.get_redis())

    asyncio.run(_grab())
    asyncio.run(_grab())

    assert pools[0] is not pools[1]


def test_close_redis_drops_only_the_current_loops_pool():
    async def _open_close_open():
        first = await core_redis.get_redis()
        await core_redis.close_redis()
        second = await core_redis.get_redis()
        return first is second

    assert asyncio.run(_open_close_open()) is False


def test_worker_run_async_closes_the_pool_before_the_loop_goes_away():
    async def _use_redis():
        await core_redis.get_redis()
        return "done"

    assert tasks._run_async(_use_redis()) == "done"
    assert len(core_redis._pools) == 0


def test_worker_run_async_closes_the_pool_even_when_the_task_fails():
    async def _fail():
        await core_redis.get_redis()
        raise RuntimeError("poll blew up")

    try:
        tasks._run_async(_fail())
    except RuntimeError as exc:
        assert "poll blew up" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected the task error to propagate")

    assert len(core_redis._pools) == 0
