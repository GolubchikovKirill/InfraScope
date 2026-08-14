from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""

_RENEW_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""


async def acquire_redis_lock(redis: Any, key: str, *, ttl_seconds: int) -> str | None:
    """Atomically acquire a lock and return its owner token."""

    owner = uuid.uuid4().hex
    acquired = await redis.set(key, owner, ex=max(ttl_seconds, 1), nx=True)
    return owner if acquired else None


async def release_redis_lock(redis: Any, key: str, owner: str) -> None:
    """Release a lock only when it is still owned by this operation."""

    try:
        await redis.eval(_RELEASE_SCRIPT, 1, key, owner)
    except Exception:
        logger.warning("Failed to release Redis lock %s; TTL will clear it", key, exc_info=True)


async def renew_redis_lock(redis: Any, key: str, owner: str, *, ttl_seconds: int) -> bool | None:
    """Extend a lock only if this operation is still its owner."""

    try:
        renewed = await redis.eval(_RENEW_SCRIPT, 1, key, owner, max(ttl_seconds, 1))
        return bool(renewed)
    except Exception:
        logger.warning("Failed to renew Redis lock %s", key, exc_info=True)
        # None means a transport failure; the caller will retry while the
        # existing TTL still protects the operation.
        return None
