"""probe_host_ports_async: the bulk pollers' probe. Same verdicts as the sync
probe, but every port of one attempt at once and nothing on a thread."""

from __future__ import annotations

import asyncio
import socket
import time

import pytest

from app.domains.inventory import reachability
from app.domains.inventory.reachability import (
    REASON_DNS_UNRESOLVED,
    REASON_NO_RESPONSE,
    REASON_NO_ROUTE,
    REASON_PORT_CLOSED,
    probe_host_ports_async,
)


@pytest.fixture
def listening_port():
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        yield server.getsockname()[1]


@pytest.fixture
def closed_port():
    # A freed port: nothing bound, so the kernel answers a connect with RST.
    # Bound-but-not-listening only does that on Linux; macOS drops the SYN
    # and the probe times out instead.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    yield port


@pytest.mark.asyncio
async def test_one_open_port_among_closed_ones_is_online(listening_port, closed_port) -> None:
    result = await probe_host_ports_async("127.0.0.1", ports=(closed_port, listening_port), timeout=1.0)

    assert result.is_online is True
    assert result.resolved_address == "127.0.0.1"


@pytest.mark.asyncio
async def test_a_refusing_host_is_port_closed_not_a_path_failure(closed_port) -> None:
    result = await probe_host_ports_async("127.0.0.1", ports=(closed_port,), timeout=1.0, max_attempts=1)

    assert result.is_online is False
    assert result.reason == REASON_PORT_CLOSED
    assert result.is_path_failure is False


@pytest.mark.asyncio
async def test_ports_are_tried_together_so_a_silent_host_costs_one_timeout(monkeypatch) -> None:
    async def _silent(_address, _port, timeout, _scope):
        await asyncio.sleep(timeout)
        return REASON_NO_RESPONSE

    monkeypatch.setattr(reachability, "_async_port_probe", _silent)

    started = time.monotonic()
    result = await probe_host_ports_async(
        "10.0.0.9", ports=(445, 3389, 135), timeout=0.3, max_attempts=1, retry_backoff_seconds=0
    )

    assert result.reason == REASON_NO_RESPONSE
    assert time.monotonic() - started < 0.6, "three ports in sequence would take 0.9 s"


@pytest.mark.asyncio
async def test_no_route_on_any_port_ends_the_probe(monkeypatch) -> None:
    calls: list[int] = []

    async def _probe(_address, port, _timeout, _scope):
        calls.append(port)
        return REASON_NO_ROUTE if port == 445 else REASON_NO_RESPONSE

    monkeypatch.setattr(reachability, "_async_port_probe", _probe)

    result = await probe_host_ports_async("10.0.0.6", ports=(445, 3389), timeout=0.1, max_attempts=3)

    assert result.reason == REASON_NO_ROUTE
    assert result.is_path_failure is True
    assert len(calls) == 2, "one attempt, no retries"


@pytest.mark.asyncio
async def test_the_verdict_is_the_last_ports_reason_like_the_sync_probe(monkeypatch) -> None:
    async def _probe(_address, port, _timeout, _scope):
        return REASON_PORT_CLOSED if port == 445 else REASON_NO_RESPONSE

    monkeypatch.setattr(reachability, "_async_port_probe", _probe)

    result = await probe_host_ports_async("10.0.0.7", ports=(445, 3389), timeout=0.1, max_attempts=1)

    assert result.reason == REASON_NO_RESPONSE


@pytest.mark.asyncio
async def test_each_attempt_widens_the_timeout(monkeypatch) -> None:
    timeouts: list[float] = []

    async def _probe(_address, _port, timeout, _scope):
        timeouts.append(timeout)
        return REASON_NO_RESPONSE

    monkeypatch.setattr(reachability, "_async_port_probe", _probe)

    await probe_host_ports_async(
        "10.0.0.8", ports=(445,), timeout=1.0, max_attempts=3, retry_backoff_seconds=0.0, timeout_multiplier=2.0
    )

    assert timeouts == [1.0, 2.0, 4.0]


@pytest.mark.asyncio
async def test_an_ip_literal_skips_the_resolver(monkeypatch, listening_port) -> None:
    def _explode(*_a, **_kw):
        raise AssertionError("an IP literal must not be resolved")

    monkeypatch.setattr(reachability, "resolve_hostname", _explode)

    assert (await probe_host_ports_async("127.0.0.1", ports=(listening_port,), timeout=1.0)).is_online


@pytest.mark.asyncio
async def test_an_unresolvable_name_never_touches_the_network(monkeypatch) -> None:
    monkeypatch.setattr(reachability, "resolve_hostname", lambda *_a, **_kw: None)

    async def _explode(*_a, **_kw):
        raise AssertionError("must not probe a name that does not resolve")

    monkeypatch.setattr(reachability, "_async_port_probe", _explode)

    result = await probe_host_ports_async("nowhere", ports=(445,), timeout=0.1)

    assert result.reason == REASON_DNS_UNRESOLVED
