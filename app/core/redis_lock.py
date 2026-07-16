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
