from __future__ import annotations

import logging

from pydantic import BaseModel

from app.core.redis import get_redis

logger = logging.getLogger(__name__)


async def get_cached_model[TModel: BaseModel](cache_key: str, model_type: type[TModel]) -> TModel | None:
    try:
        redis = await get_redis()
        cached = await redis.get(cache_key)
        if cached:
            return model_type.model_validate_json(cached)
    except Exception as exc:
        logger.debug("Cache read failed for %s: %s", cache_key, exc)
    return None


async def set_cached_model(cache_key: str, value: BaseModel, *, ttl: int) -> None:
    try:
        redis = await get_redis()
        await redis.setex(cache_key, ttl, value.model_dump_json())
    except Exception as exc:
        logger.debug("Cache write failed for %s: %s", cache_key, exc)


async def invalidate_entity_cache(namespace: str, *, event_id: str | None = None) -> None:
    """Invalidate Redis cache entries and notify realtime clients for one entity namespace."""
    try:
        from app.api.websockets import broadcast_event

        await broadcast_event("invalidate", event_id or namespace)
        redis = await get_redis()
        keys = []
        async for key in redis.scan_iter(f"{namespace}:*"):
            keys.append(key)
        if keys:
            await redis.delete(*keys)
    except Exception as exc:
        logger.warning("%s cache invalidation failed: %s", namespace, exc)
