"""Short-lived Redis cache for list endpoints, one hash per entity namespace.

Layout: every namespace ("printers", "switch_ports:<id>", ...) is one Redis hash
``cache:<namespace>`` whose fields are the query variants (filter/page) and whose
values are the response JSON exactly as it goes out on the wire.

Why a hash and not one key per variant (the previous layout):

- Invalidation is a single ``DEL`` - O(1) round trips. The old one walked the
  whole keyspace with ``SCAN namespace:*`` on every poll cycle and every edit,
  i.e. O(total keys in Redis) with locks, rate limits, JWT blacklist and the
  poll-resilience state all in the same database.
- A cache hit returns the stored bytes as the response body. The old path parsed
  them back into Pydantic models only for FastAPI to validate and serialize the
  very same data again - for 200 printers that was most of the request's CPU.

The hash's TTL is set once, when it is created (``EXPIRE ... NX``), so no entry
outlives ``ttl`` seconds; a later write never extends the life of older ones.
"""

from __future__ import annotations

import logging

from fastapi import Response
from pydantic import BaseModel

from app.core.redis import REDIS_ERRORS, get_redis

logger = logging.getLogger(__name__)

_JSON = "application/json"


class EntityCache:
    """Response cache for one entity namespace. Every Redis failure fails open:
    a cache that is down means a slower request, never a failed one."""

    __slots__ = ("namespace", "ttl")

    def __init__(self, namespace: str, *, ttl: int = 30) -> None:
        self.namespace = namespace
        self.ttl = ttl

    @property
    def redis_key(self) -> str:
        return f"cache:{self.namespace}"

    async def get_response(self, variant: str) -> Response | None:
        """The cached body for this query variant as a ready response, or None."""
        try:
            redis = await get_redis()
            payload = await redis.hget(self.redis_key, variant)
        except REDIS_ERRORS as exc:
            logger.debug("Cache read failed for %s/%s: %s", self.namespace, variant, exc)
            return None
        if not payload:
            return None
        return Response(content=payload, media_type=_JSON)

    async def respond(self, variant: str, value: BaseModel) -> Response:
        """Serialize `value` once, store it, and return it as the response.

        by_alias matches FastAPI's own response_model serialization, so a hit
        and a miss produce byte-identical bodies.
        """
        payload = value.model_dump_json(by_alias=True)
        try:
            redis = await get_redis()
            async with redis.pipeline(transaction=False) as pipe:
                pipe.hset(self.redis_key, variant, payload)
                pipe.expire(self.redis_key, self.ttl, nx=True)
                await pipe.execute()
        except REDIS_ERRORS as exc:
            logger.debug("Cache write failed for %s/%s: %s", self.namespace, variant, exc)
        return Response(content=payload, media_type=_JSON)

    async def clear(self) -> None:
        redis = await get_redis()
        await redis.delete(self.redis_key)


async def invalidate_entity_cache(namespace: str, *, event_id: str | None = None) -> None:
    """Drop a namespace's cached responses, then tell realtime clients to refetch.

    The order matters: announcing first let a browser refetch in the gap and get
    the stale cached page back, which it then kept until the next change.
    """
    from app.api.websockets import broadcast_event

    try:
        await EntityCache(namespace).clear()
    except REDIS_ERRORS as exc:
        logger.warning("%s cache invalidation failed: %s", namespace, exc)
    await broadcast_event("invalidate", event_id or namespace)
