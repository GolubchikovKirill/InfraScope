"""SnmpEngine opens a UDP socket lazily on first request and never closes it
on its own. Every call site that creates one must close it in a finally
block, in the same event loop that issued the request - the incident this
guards against was ~1945 leaked UDP sockets in polling-service hitting the
container's 1024 FD limit (OSError: [Errno 24] Too many open files),
turning every printer/media-player/cash-register poll into a 500.

Each test here fakes SnmpEngine itself (never touches a real socket) and
asserts closeDispatcher() ran exactly once, on both the success path and
the exception path - the leak only mattered under real polling load, where
failures (unreachable/misconfigured devices) are the common case, not the
exception.
"""

from __future__ import annotations

import pytest


class _FakeEngine:
    instances: list["_FakeEngine"] = []

    def __init__(self):
        self.close_calls = 0
        _FakeEngine.instances.append(self)

    def closeDispatcher(self):
        self.close_calls += 1


@pytest.fixture(autouse=True)
def _reset_fake_engine():
    _FakeEngine.instances.clear()
    yield
    _FakeEngine.instances.clear()


@pytest.mark.asyncio
async def test_get_snmp_mac_closes_engine_on_success(monkeypatch):
    from app.services.snmp import mac as mac_module

    monkeypatch.setattr(mac_module, "SnmpEngine", _FakeEngine)

    async def _fake_walk(*_a, **_kw):
        return
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(mac_module, "walkCmd", _fake_walk)

    result = await mac_module._get_snmp_mac_async("10.0.0.5")

    assert result is None  # empty walk -> no MAC found, not the point of this test
    assert len(_FakeEngine.instances) == 1
    assert _FakeEngine.instances[0].close_calls == 1


@pytest.mark.asyncio
async def test_get_snmp_mac_closes_engine_when_walk_raises(monkeypatch):
    from app.services.snmp import mac as mac_module

    monkeypatch.setattr(mac_module, "SnmpEngine", _FakeEngine)

    def _raising_walk(*_a, **_kw):
        raise RuntimeError("device unreachable")

    monkeypatch.setattr(mac_module, "walkCmd", _raising_walk)

    await mac_module._get_snmp_mac_async("10.0.0.6")

    assert _FakeEngine.instances[0].close_calls == 1


@pytest.mark.asyncio
async def test_poll_printer_closes_engine_when_target_creation_fails(monkeypatch):
    """Regression case for the pre-fix bug: this branch returns before any
    SNMP traffic is even attempted, which is exactly the kind of early
    return that silently skipped closeDispatcher() before the fix wrapped
    the whole function body in try/finally."""
    from app.services.snmp import poller as poller_module

    monkeypatch.setattr(poller_module, "SnmpEngine", _FakeEngine)

    def _raise(*_a, **_kw):
        raise ValueError("bad target")

    monkeypatch.setattr(poller_module, "UdpTransportTarget", _raise)

    result = await poller_module._poll_printer_async("10.0.0.7")

    assert result.is_online is False
    assert _FakeEngine.instances[0].close_calls == 1


@pytest.mark.asyncio
async def test_poll_printer_closes_engine_when_snmp_get_raises(monkeypatch):
    from app.services.snmp import poller as poller_module

    monkeypatch.setattr(poller_module, "SnmpEngine", _FakeEngine)
    monkeypatch.setattr(poller_module, "UdpTransportTarget", lambda *a, **kw: object())

    async def _raising_get(*_a, **_kw):
        raise RuntimeError("timeout")

    monkeypatch.setattr(poller_module, "_snmp_get", _raising_get)

    with pytest.raises(RuntimeError):
        await poller_module._poll_printer_async("10.0.0.8")

    assert _FakeEngine.instances[0].close_calls == 1


@pytest.mark.asyncio
async def test_poll_printer_light_closes_engine_on_success(monkeypatch):
    from app.services.snmp import poller as poller_module

    monkeypatch.setattr(poller_module, "SnmpEngine", _FakeEngine)
    monkeypatch.setattr(poller_module, "UdpTransportTarget", lambda *a, **kw: object())

    async def _fake_get(*_a, **_kw):
        return "Some Printer Descr"

    monkeypatch.setattr(poller_module, "_snmp_get", _fake_get)

    result = await poller_module._poll_printer_light_async("10.0.0.9")

    assert result.is_online is True
    assert _FakeEngine.instances[0].close_calls == 1


@pytest.mark.asyncio
async def test_switch_fetch_basics_closes_engine_on_success(monkeypatch):
    from app.services.switches import snmp_provider as snmp_provider_module

    provider = snmp_provider_module.SnmpSwitchProvider()
    monkeypatch.setattr(snmp_provider_module, "SnmpEngine", _FakeEngine)

    async def _fake_create_target(*_a, **_kw):
        return object()

    monkeypatch.setattr(provider, "_create_transport_target", _fake_create_target)

    async def _fake_get(_engine, _target, _comm, oid):
        return "sysname" if "1.5.0" in oid else None

    monkeypatch.setattr(provider, "_snmp_get", _fake_get)

    result = await provider._fetch_basics(host="10.0.0.10", community="public")

    assert result is not None
    assert _FakeEngine.instances[0].close_calls == 1


@pytest.mark.asyncio
async def test_switch_fetch_basics_closes_engine_when_get_raises(monkeypatch):
    from app.services.switches import snmp_provider as snmp_provider_module

    provider = snmp_provider_module.SnmpSwitchProvider()
    monkeypatch.setattr(snmp_provider_module, "SnmpEngine", _FakeEngine)

    async def _fake_create_target(*_a, **_kw):
        return object()

    monkeypatch.setattr(provider, "_create_transport_target", _fake_create_target)

    async def _raising_get(*_a, **_kw):
        raise RuntimeError("no route to host")

    monkeypatch.setattr(provider, "_snmp_get", _raising_get)

    with pytest.raises(RuntimeError):
        await provider._fetch_basics(host="10.0.0.11", community="public")

    assert _FakeEngine.instances[0].close_calls == 1


@pytest.mark.asyncio
async def test_switch_get_ports_closes_engine_even_when_a_walk_raises(monkeypatch):
    from app.services.switches import snmp_provider as snmp_provider_module
    from app.domains.inventory.models import NetworkSwitch

    provider = snmp_provider_module.SnmpSwitchProvider()
    monkeypatch.setattr(snmp_provider_module, "SnmpEngine", _FakeEngine)

    async def _fake_create_target(*_a, **_kw):
        return object()

    monkeypatch.setattr(provider, "_create_transport_target", _fake_create_target)

    async def _raising_walk(*_a, **_kw):
        raise RuntimeError("switch dropped mid-walk")

    monkeypatch.setattr(provider, "_snmp_walk", _raising_walk)

    switch = NetworkSwitch(name="sw1", ip_address="10.0.0.12")

    with pytest.raises(RuntimeError):
        await provider._get_ports_async(switch)

    assert _FakeEngine.instances[0].close_calls == 1


@pytest.mark.asyncio
async def test_switch_snmp_set_closes_engine_when_target_creation_fails(monkeypatch):
    from app.services.switches import snmp_provider as snmp_provider_module

    provider = snmp_provider_module.SnmpSwitchProvider()
    monkeypatch.setattr(snmp_provider_module, "SnmpEngine", _FakeEngine)

    async def _raise(*_a, **_kw):
        raise ValueError("bad host")

    monkeypatch.setattr(provider, "_create_transport_target", _raise)

    with pytest.raises(ValueError):
        await provider._snmp_set(host="10.0.0.13", community="public", oid="1.3.6.1", value=1)

    assert _FakeEngine.instances[0].close_calls == 1
