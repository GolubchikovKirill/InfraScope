from __future__ import annotations

import socket
import time

import pytest
from pydantic import BaseModel

from app.core.redis import get_redis
from app.services import cache as cache_module
from app.services.cache import EntityCache, invalidate_entity_cache
from app.services.snmp.tcp_fallback import _tcp_any_port_open


class _Page(BaseModel):
    data: list[str]
    count: int


@pytest.mark.asyncio
async def test_a_hit_returns_the_exact_bytes_the_miss_sent() -> None:
    cache = EntityCache("widgets", ttl=30)
    assert await cache.get_response("a:0:10") is None

    miss = await cache.respond("a:0:10", _Page(data=["x", "y"], count=2))
    hit = await cache.get_response("a:0:10")

    assert hit is not None
    assert hit.body == miss.body == b'{"data":["x","y"],"count":2}'
    assert hit.media_type == "application/json"


@pytest.mark.asyncio
async def test_the_namespace_ttl_is_set_once_and_never_extended() -> None:
    cache = EntityCache("widgets", ttl=30)
    redis = await get_redis()

    await cache.respond("a", _Page(data=[], count=0))
    await redis.expire(cache.redis_key, 5)  # pretend 25 s have passed
    await cache.respond("b", _Page(data=[], count=0))

    assert await redis.ttl(cache.redis_key) <= 5


@pytest.mark.asyncio
async def test_invalidation_drops_every_variant_but_only_of_its_namespace(monkeypatch) -> None:
    events: list[str] = []

    async def _record(_event, item_id, payload=None):
        # The cache must already be empty when clients are told to refetch.
        events.append((item_id, await EntityCache("widgets").get_response("a")))

    monkeypatch.setattr("app.api.websockets.broadcast_event", _record)
    widgets, gadgets = EntityCache("widgets"), EntityCache("gadgets")
    await widgets.respond("a", _Page(data=[], count=0))
    await widgets.respond("b", _Page(data=[], count=0))
    await gadgets.respond("a", _Page(data=[], count=0))

    await invalidate_entity_cache("widgets")

    assert await widgets.get_response("a") is None
    assert await widgets.get_response("b") is None
    assert await gadgets.get_response("a") is not None
    assert events == [("widgets", None)]


@pytest.mark.asyncio
async def test_a_redis_outage_degrades_to_no_cache(monkeypatch) -> None:
    async def _down():
        raise ConnectionError("refused")

    monkeypatch.setattr(cache_module, "get_redis", _down)
    cache = EntityCache("widgets")

    assert await cache.get_response("a") is None
    response = await cache.respond("a", _Page(data=["x"], count=1))
    assert response.body == b'{"data":["x"],"count":1}'


def test_tcp_probe_finds_the_one_open_port_among_closed_ones() -> None:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        open_port = server.getsockname()[1]
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            closed_port = probe.getsockname()[1]  # bound, not listening: refuses

        assert _tcp_any_port_open("127.0.0.1", (closed_port, open_port)) is True
        assert _tcp_any_port_open("127.0.0.1", (closed_port,)) is False


def test_tcp_probe_on_a_bad_address_is_simply_closed() -> None:
    started = time.monotonic()
    assert _tcp_any_port_open("definitely not a host", (80, 443)) is False
    assert time.monotonic() - started < 5
