from __future__ import annotations

import logging

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.services import poll_resilience


def _broken(exc: Exception):
    async def get_redis():
        raise exc

    return get_redis


@pytest.mark.asyncio
async def test_circuit_check_treats_a_redis_outage_as_closed_and_says_so(monkeypatch, caplog) -> None:
    monkeypatch.setattr(poll_resilience, "get_redis", _broken(RedisConnectionError("refused")))

    with caplog.at_level(logging.WARNING, logger=poll_resilience.logger.name):
        assert await poll_resilience.is_circuit_open("switch", "sw-1") is False

    assert "switch/sw-1" in caplog.text and "refused" in caplog.text


@pytest.mark.asyncio
async def test_a_socket_level_failure_is_also_a_redis_outage(monkeypatch) -> None:
    monkeypatch.setattr(poll_resilience, "get_redis", _broken(TimeoutError()))

    assert await poll_resilience.is_circuit_open("switch", "sw-1") is False


@pytest.mark.asyncio
async def test_a_real_bug_is_not_swallowed_as_an_outage(monkeypatch) -> None:
    # "Event loop is closed" once hid behind a blanket `except Exception` here
    monkeypatch.setattr(poll_resilience, "get_redis", _broken(RuntimeError("Event loop is closed")))

    with pytest.raises(RuntimeError, match="Event loop is closed"):
        await poll_resilience.is_circuit_open("switch", "sw-1")


@pytest.mark.asyncio
async def test_poll_outcome_still_decides_from_the_probe_when_redis_is_down(monkeypatch) -> None:
    monkeypatch.setattr(poll_resilience, "get_redis", _broken(RedisConnectionError("refused")))

    online = await poll_resilience.apply_poll_outcome(
        kind="switch",
        entity_id="sw-1",
        previous_effective_online=False,
        probed_online=True,
        probed_error=False,
    )

    assert online is True
