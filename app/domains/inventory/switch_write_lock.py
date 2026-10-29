"""The per-switch lease every hardware write takes, from the API and the worker alike.

One holder at a time per switch: a PoE cycle, a port change and a camera
sweep must not drive the same switch over SSH at once. The lease is renewed
for as long as its holder runs and expires on its own if the holder dies.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import suppress
from dataclasses import dataclass

from app.core.config import settings
from app.core.redis import REDIS_ERRORS, get_redis
from app.core.redis_lock import acquire_redis_lock, release_redis_lock, renew_redis_lock

logger = logging.getLogger(__name__)

_MIN_SWITCH_WRITE_LEASE_SECONDS = 300


@dataclass
class SwitchWriteLease:
    key: str
    owner: str
    ttl_seconds: int
    renewal_task: asyncio.Task[None] | None = None


def switch_write_lock_key(switch_id: uuid.UUID | str) -> str:
    return f"lock:switch-write:{switch_id}"


async def _renew_switch_write_lease(lease: SwitchWriteLease) -> None:
    """Keep a live hardware-operation lease alive until its holder exits."""

    interval = max(1, min(30, lease.ttl_seconds // 3))
    while True:
        try:
            await asyncio.sleep(interval)
            redis = await asyncio.wait_for(get_redis(), timeout=0.2)
            renewed = await asyncio.wait_for(
                renew_redis_lock(redis, lease.key, lease.owner, ttl_seconds=lease.ttl_seconds),
                timeout=0.3,
            )
            if renewed is False:
                # Never delete a lease that another request has obtained.
                return
        except asyncio.CancelledError:
            raise
        except REDIS_ERRORS as exc:
            # New writes fail closed if Redis is unavailable. Keep retrying
            # while the current TTL protects this in-flight operation.
            logger.warning("Could not renew switch write lease %s: %s", lease.key, exc)
            continue


async def acquire_switch_write_lease(switch_id: uuid.UUID | str) -> SwitchWriteLease | None:
    """The lease, or None while another operation holds it.

    Raises when Redis cannot be reached: a process-local fallback would let
    separate API workers power-cycle the same switch concurrently, so callers
    must fail closed.
    """
    key = switch_write_lock_key(switch_id)
    redis = await asyncio.wait_for(get_redis(), timeout=0.2)
    ttl_seconds = max(int(settings.SWITCH_WRITE_LOCK_SECONDS), _MIN_SWITCH_WRITE_LEASE_SECONDS)
    owner = await asyncio.wait_for(acquire_redis_lock(redis, key, ttl_seconds=ttl_seconds), timeout=0.3)
    if owner is None:
        return None
    lease = SwitchWriteLease(key=key, owner=owner, ttl_seconds=ttl_seconds)
    lease.renewal_task = asyncio.create_task(_renew_switch_write_lease(lease))
    return lease


async def release_switch_write_lease(lease: SwitchWriteLease | None) -> None:
    if lease is None:
        return
    if lease.renewal_task is not None:
        lease.renewal_task.cancel()
        with suppress(asyncio.CancelledError):
            await lease.renewal_task
    try:
        redis = await asyncio.wait_for(get_redis(), timeout=0.2)
        await asyncio.wait_for(release_redis_lock(redis, lease.key, lease.owner), timeout=0.3)
    except REDIS_ERRORS as exc:
        # The lease expires safely if Redis cannot be reached during cleanup.
        logger.warning("Could not release switch write lease %s: %s", lease.key, exc)


async def switch_write_lease_held(switch_id: uuid.UUID | str) -> bool:
    """Whether some operation holds the switch right now (a read, for an early 409)."""
    try:
        redis = await asyncio.wait_for(get_redis(), timeout=0.2)
        return bool(await asyncio.wait_for(redis.exists(switch_write_lock_key(switch_id)), timeout=0.3))
    except REDIS_ERRORS:
        return False
