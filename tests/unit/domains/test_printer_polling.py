from __future__ import annotations

import asyncio
from datetime import datetime
from typing import ClassVar, cast

import pytest

from app.domains.inventory.models import Printer
from app.domains.inventory.printer_polling import (
    _apply_full_printer_result,
    _apply_light_printer_result,
    _printer_offline_reason,
    _subnets_with_total_failure,
    is_full_poll_cycle,
    poll_all_printers_local,
    poll_one_printer,
    poll_printer_batch,
    poll_single_printer_local,
    verify_printer_mac,
)
from app.domains.inventory.reachability import ReachabilityResult
from app.services.snmp import PrinterStatus
from app.services.snmp._pysnmp_compat import SnmpEngine


class _NoLockRedis:
    """Just enough for poll_all_printers_local's lock acquire/release -
    always grants the lock, never blocks a test on real Redis."""

    async def set(self, *_a, **_kw):
        return True

    async def delete(self, *_a, **_kw):
        return None


class _FakeResilienceRedis:
    """In-memory stand-in for poll_resilience.apply_poll_outcome's Redis
    usage, so consecutive-failure state actually persists across calls
    within a test instead of silently resetting (apply_poll_outcome treats
    a Redis error as "no state yet", which would make every cycle look like
    the first failure)."""

    def __init__(self):
        self.hashes: dict[str, dict[str, str]] = {}

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    async def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    async def hset(self, key, mapping):
        self.hashes.setdefault(key, {}).update({k: str(v) for k, v in mapping.items()})

    async def expire(self, *_a, **_kw):
        return None


def test_verify_printer_mac_records_first_seen_mac() -> None:
    printer = Printer(
        printer_type="laser",
        connection_type="ip",
        store_name="Store A",
        model="HP",
        ip_address="10.10.10.10",
    )

    status = verify_printer_mac(printer, "aa:bb:cc:dd:ee:ff")

    assert status == "verified"
    assert printer.mac_address == "aa:bb:cc:dd:ee:ff"


def test_verify_printer_mac_detects_mismatch() -> None:
    printer = Printer(
        printer_type="laser",
        connection_type="ip",
        store_name="Store A",
        model="HP",
        ip_address="10.10.10.10",
        mac_address="aa:bb:cc:dd:ee:ff",
    )

    status = verify_printer_mac(printer, "11:22:33:44:55:66")

    assert status == "mismatch"
    assert printer.mac_address == "aa:bb:cc:dd:ee:ff"


class _FakeEngine:
    """Stands in for SnmpEngine: records how many exist and whether each was closed."""

    created: ClassVar[list[_FakeEngine]] = []

    def __init__(self) -> None:
        self.closed = False
        _FakeEngine.created.append(self)

    def close_dispatcher(self) -> None:
        self.closed = True


@pytest.fixture
def fake_engines(monkeypatch):
    _FakeEngine.created = []
    monkeypatch.setattr("app.domains.inventory.printer_polling.SnmpEngine", _FakeEngine)
    return _FakeEngine.created


def _label_printer(name: str, ip: str) -> Printer:
    return Printer(printer_type="label", connection_type="ip", store_name=name, model="Zebra", ip_address=ip)


@pytest.mark.asyncio
async def test_poll_printer_batch_preserves_result_for_each_ip(monkeypatch, fake_engines) -> None:
    printers = [_label_printer("Label A", "10.10.10.20"), _label_printer("Label B", "10.10.10.21")]

    async def fake_poll_one(printer: Printer, engine, *, full: bool = True):
        del engine, full
        online = (printer.ip_address or "").endswith(".20")
        return printer.ip_address, PrinterStatus(is_online=online, status="online" if online else "offline"), None

    monkeypatch.setattr("app.domains.inventory.printer_polling.poll_one_printer", fake_poll_one)

    result = await poll_printer_batch(printers)

    assert result == {
        "10.10.10.20": (PrinterStatus(is_online=True, status="online"), None),
        "10.10.10.21": (PrinterStatus(is_online=False, status="offline"), None),
    }


@pytest.mark.asyncio
async def test_poll_printer_batch_shares_one_engine_and_closes_it(monkeypatch, fake_engines) -> None:
    printers = [_label_printer(f"L{i}", f"10.10.10.{i}") for i in range(20, 26)]
    seen: list[object] = []

    async def fake_poll_one(printer: Printer, engine, *, full: bool = True):
        del full
        seen.append(engine)
        return printer.ip_address, None, None

    monkeypatch.setattr("app.domains.inventory.printer_polling.poll_one_printer", fake_poll_one)

    await poll_printer_batch(printers)

    assert len(fake_engines) == 1, "one engine per cycle, not one per printer"
    assert all(engine is fake_engines[0] for engine in seen) and len(seen) == 6
    assert fake_engines[0].closed is True


@pytest.mark.asyncio
async def test_poll_printer_batch_bounds_how_many_printers_are_in_flight(monkeypatch, fake_engines) -> None:
    monkeypatch.setattr("app.domains.inventory.printer_polling.settings.PRINTER_POLL_MAX_WORKERS", 3)
    printers = [_label_printer(f"L{i}", f"10.10.10.{i}") for i in range(30, 42)]
    running = {"now": 0, "peak": 0}

    async def slow_poll_one(printer: Printer, engine, *, full: bool = True):
        del engine, full
        running["now"] += 1
        running["peak"] = max(running["peak"], running["now"])
        await asyncio.sleep(0.01)
        running["now"] -= 1
        return printer.ip_address, None, None

    monkeypatch.setattr("app.domains.inventory.printer_polling.poll_one_printer", slow_poll_one)

    result = await poll_printer_batch(printers)

    assert len(result) == 12
    assert running["peak"] == 3


@pytest.mark.asyncio
async def test_poll_printer_batch_survives_one_printer_raising(monkeypatch, fake_engines) -> None:
    printers = [_label_printer("Bad", "10.10.10.60"), _label_printer("Good", "10.10.10.61")]

    async def fake_poll_one(printer: Printer, engine, *, full: bool = True):
        del engine, full
        if (printer.ip_address or "").endswith(".60"):
            raise RuntimeError("boom")
        return printer.ip_address, PrinterStatus(is_online=True, status="online"), None

    monkeypatch.setattr("app.domains.inventory.printer_polling.poll_one_printer", fake_poll_one)

    result = await poll_printer_batch(printers)

    assert result["10.10.10.60"] == (None, None)
    assert result["10.10.10.61"] == (PrinterStatus(is_online=True, status="online"), None)
    assert fake_engines[0].closed is True


@pytest.mark.asyncio
async def test_poll_printer_batch_of_nothing_opens_no_engine(fake_engines) -> None:
    assert await poll_printer_batch([]) == {}
    assert fake_engines == []


def test_is_full_poll_cycle_true_at_top_of_hour(monkeypatch) -> None:
    monkeypatch.setattr("app.core.config.settings.PRINTER_FULL_POLL_EVERY_N_CYCLES", 4)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 7, 24, 10, 0, tzinfo=tz)

    monkeypatch.setattr("app.domains.inventory.printer_polling.datetime", _FrozenDatetime)
    assert is_full_poll_cycle() is True


def test_is_full_poll_cycle_false_between_full_cycles(monkeypatch) -> None:
    monkeypatch.setattr("app.core.config.settings.PRINTER_FULL_POLL_EVERY_N_CYCLES", 4)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 7, 24, 10, 15, tzinfo=tz)

    monkeypatch.setattr("app.domains.inventory.printer_polling.datetime", _FrozenDatetime)
    assert is_full_poll_cycle() is False


@pytest.mark.asyncio
async def test_poll_one_printer_light_skips_toner_and_mac_calls(monkeypatch) -> None:
    printer = Printer(
        printer_type="laser",
        connection_type="ip",
        store_name="Store A",
        model="HP",
        ip_address="10.10.10.30",
    )

    async def _light(engine, ip, community):
        return PrinterStatus(is_online=True, status="online")

    async def _jitter():
        return None

    async def _must_not_be_called(*_a, **_kw):
        raise AssertionError("full poll and MAC lookup must not run on a light cycle")

    monkeypatch.setattr("app.domains.inventory.printer_polling.poll_printer_light_async", _light)
    monkeypatch.setattr("app.domains.inventory.printer_polling.poll_jitter_async", _jitter)
    monkeypatch.setattr("app.domains.inventory.printer_polling.poll_printer_async", _must_not_be_called)
    monkeypatch.setattr("app.domains.inventory.printer_polling.get_snmp_mac_async", _must_not_be_called)

    ip, result, mac = await poll_one_printer(printer, cast(SnmpEngine, object()), full=False)

    assert ip == "10.10.10.30"
    assert result is not None and result.is_online is True
    assert mac is None


@pytest.mark.asyncio
async def test_poll_one_printer_full_asks_for_the_mac_only_when_online(monkeypatch) -> None:
    printer = Printer(
        printer_type="laser", connection_type="ip", store_name="S", model="HP", ip_address="10.10.10.31"
    )
    online = {"value": True}
    mac_calls: list[str] = []

    async def _full(engine, ip, community):
        return PrinterStatus(is_online=online["value"], status="online")

    async def _mac(engine, ip, community):
        mac_calls.append(ip)
        return "aa:bb:cc:dd:ee:ff"

    async def _jitter():
        return None

    monkeypatch.setattr("app.domains.inventory.printer_polling.poll_printer_async", _full)
    monkeypatch.setattr("app.domains.inventory.printer_polling.get_snmp_mac_async", _mac)
    monkeypatch.setattr("app.domains.inventory.printer_polling.poll_jitter_async", _jitter)

    _, _, mac = await poll_one_printer(printer, cast(SnmpEngine, object()))
    assert mac == "aa:bb:cc:dd:ee:ff" and mac_calls == ["10.10.10.31"]

    online["value"] = False
    _, result, mac = await poll_one_printer(printer, cast(SnmpEngine, object()))
    assert mac is None and result is not None and result.is_online is False and mac_calls == ["10.10.10.31"]


def test_apply_light_printer_result_preserves_toner_levels() -> None:
    printer = Printer(
        printer_type="laser",
        connection_type="ip",
        store_name="Store A",
        model="HP",
        ip_address="10.10.10.30",
        toner_black=42,
        mac_status="verified",
    )
    light_result = PrinterStatus(is_online=True, status="online")

    _apply_light_printer_result(printer, light_result)

    assert printer.is_online is True
    assert printer.toner_black == 42
    assert printer.mac_status == "verified"


def test_whole_subnet_failing_at_once_is_flagged_as_a_path_problem(monkeypatch) -> None:
    """Printers don't all fail inside one 15-minute window - the path does."""
    monkeypatch.setattr("app.domains.inventory.printer_polling.settings.POLL_PATH_FAILURE_MIN_DEVICES", 3)
    monkeypatch.setattr("app.domains.inventory.printer_polling.settings.POLL_PATH_FAILURE_RATIO", 0.8)

    results: dict[str, tuple[PrinterStatus | ReachabilityResult | None, str | None]] = {
        "10.10.98.10": (None, None),
        "10.10.98.11": (None, None),
        "10.10.98.12": (None, None),
        "10.10.98.13": (None, None),
    }

    assert _subnets_with_total_failure(results) == {"10.10.98"}


def test_one_printer_down_among_healthy_neighbours_is_not_a_path_problem(monkeypatch) -> None:
    monkeypatch.setattr("app.domains.inventory.printer_polling.settings.POLL_PATH_FAILURE_MIN_DEVICES", 3)
    monkeypatch.setattr("app.domains.inventory.printer_polling.settings.POLL_PATH_FAILURE_RATIO", 0.8)

    results = {
        "10.10.98.10": (None, None),
        "10.10.98.11": (PrinterStatus(is_online=True, status="online"), None),
        "10.10.98.12": (PrinterStatus(is_online=True, status="online"), None),
        "10.10.98.13": (PrinterStatus(is_online=True, status="online"), None),
    }

    assert _subnets_with_total_failure(results) == set()


def test_a_lone_printer_failing_is_never_treated_as_a_path_problem(monkeypatch) -> None:
    """Below the device threshold there is no evidence to tell "the printer
    broke" from "the path broke", so the normal per-device logic must run."""
    monkeypatch.setattr("app.domains.inventory.printer_polling.settings.POLL_PATH_FAILURE_MIN_DEVICES", 3)
    monkeypatch.setattr("app.domains.inventory.printer_polling.settings.POLL_PATH_FAILURE_RATIO", 0.8)

    assert _subnets_with_total_failure({"10.10.98.10": (None, None)}) == set()


def test_subnets_are_judged_independently(monkeypatch) -> None:
    monkeypatch.setattr("app.domains.inventory.printer_polling.settings.POLL_PATH_FAILURE_MIN_DEVICES", 3)
    monkeypatch.setattr("app.domains.inventory.printer_polling.settings.POLL_PATH_FAILURE_RATIO", 0.8)

    results = {
        "10.10.98.10": (None, None),
        "10.10.98.11": (None, None),
        "10.10.98.12": (None, None),
        "10.10.99.10": (PrinterStatus(is_online=True, status="online"), None),
        "10.10.99.11": (PrinterStatus(is_online=True, status="online"), None),
        "10.10.99.12": (PrinterStatus(is_online=True, status="online"), None),
    }

    assert _subnets_with_total_failure(results) == {"10.10.98"}


def test_apply_full_printer_result_stamps_toner_updated_at() -> None:
    printer = Printer(
        printer_type="laser",
        connection_type="ip",
        store_name="Store A",
        model="HP",
        ip_address="10.10.10.30",
    )
    assert printer.toner_updated_at is None
    full_result = PrinterStatus(is_online=True, status="online", toner_black=55)

    _apply_full_printer_result(printer, full_result, None)

    assert printer.toner_black == 55
    assert printer.toner_updated_at is not None


@pytest.mark.asyncio
async def test_poll_single_printer_local_retries_before_marking_offline(db_session, monkeypatch) -> None:
    printer = Printer(
        printer_type="laser",
        connection_type="ip",
        store_name="Store Retry",
        model="HP",
        ip_address="10.10.10.50",
        is_online=True,
        status="online",
    )
    db_session.add(printer)
    db_session.commit()
    db_session.refresh(printer)

    monkeypatch.setattr("app.domains.inventory.printer_polling.settings.PRINTER_MANUAL_POLL_RETRY_DELAY_SECONDS", 0)

    calls = {"count": 0}

    async def flaky_poll_one(target_printer: Printer, engine, *, full: bool = True):
        del engine, full
        calls["count"] += 1
        if calls["count"] == 1:
            return target_printer.ip_address, None, None
        return target_printer.ip_address, PrinterStatus(is_online=True, status="online", toner_black=10), "aa:bb:cc:dd:ee:ff"

    monkeypatch.setattr("app.domains.inventory.printer_polling.poll_one_printer", flaky_poll_one)

    result = await poll_single_printer_local(session=db_session, printer_id=printer.id)

    assert calls["count"] == 2
    assert result.is_online is True
    assert result.status == "online"


@pytest.mark.asyncio
async def test_poll_single_printer_local_marks_offline_after_two_failed_attempts(db_session, monkeypatch) -> None:
    printer = Printer(
        printer_type="laser",
        connection_type="ip",
        store_name="Store Retry Fail",
        model="HP",
        ip_address="10.10.10.51",
        is_online=True,
        status="online",
    )
    db_session.add(printer)
    db_session.commit()
    db_session.refresh(printer)

    monkeypatch.setattr("app.domains.inventory.printer_polling.settings.PRINTER_MANUAL_POLL_RETRY_DELAY_SECONDS", 0)

    calls = {"count": 0}

    async def always_fails(target_printer: Printer, engine, *, full: bool = True):
        del engine, full
        calls["count"] += 1
        return target_printer.ip_address, None, None

    monkeypatch.setattr("app.domains.inventory.printer_polling.poll_one_printer", always_fails)

    result = await poll_single_printer_local(session=db_session, printer_id=printer.id)

    assert calls["count"] == 2
    assert result.is_online is False
    assert result.status == "error"
    assert result.reachability_reason == "poll_error"


def test_printer_offline_reason_maps_target_creation_failure():
    """From poller.py: target construction itself failed (malformed IP) -
    distinct from a device that simply didn't answer."""
    assert _printer_offline_reason("unreachable") == "target_invalid"


def test_printer_offline_reason_defaults_to_no_response():
    """SNMP over UDP can't distinguish a wrong community string from a dead
    route the way SSH can - both time out identically, so every other
    offline case collapses to one generic reason."""
    assert _printer_offline_reason("offline") == "no_response"
    assert _printer_offline_reason(None) == "no_response"


def test_apply_full_printer_result_clears_a_stale_reachability_reason():
    printer = Printer(
        printer_type="laser",
        connection_type="ip",
        store_name="Store A",
        model="HP",
        ip_address="10.10.10.52",
        reachability_reason="no_response",
    )
    result = PrinterStatus(is_online=True, status="online", sys_description="HP LaserJet")

    _apply_full_printer_result(printer, result, current_mac=None)

    assert printer.is_online is True
    assert printer.reachability_reason is None


@pytest.mark.asyncio
async def test_bulk_poll_respects_the_offline_confirmation_grace_period(db_session, monkeypatch) -> None:
    """Regression test: _apply_full_printer_result used to be called whenever
    the resilience layer decided effective_online=True, but it unconditionally
    copies result.is_online (False, on a failed probe) onto the printer -
    silently overriding the "still within grace period" decision and
    flipping the printer offline on its very first failed poll. A single
    transient SNMP timeout should not immediately mark a previously-online
    printer offline; POLL_OFFLINE_CONFIRMATIONS (default 2) failed cycles
    are required first.
    """
    printer = Printer(
        printer_type="laser",
        connection_type="ip",
        store_name="Store A",
        model="HP",
        ip_address="10.10.10.60",
        is_online=True,
        status="online",
    )
    db_session.add(printer)
    db_session.commit()
    db_session.refresh(printer)

    async def _fake_lock_redis():
        return _NoLockRedis()

    fake_resilience_redis = _FakeResilienceRedis()

    async def _fake_resilience_redis():
        return fake_resilience_redis

    async def _noop():
        return None

    monkeypatch.setattr("app.domains.inventory.printer_polling.get_redis", _fake_lock_redis)
    monkeypatch.setattr("app.services.poll_resilience.get_redis", _fake_resilience_redis)
    monkeypatch.setattr("app.domains.inventory.printer_polling.invalidate_printer_cache", _noop)
    monkeypatch.setattr(
        "app.domains.inventory.printer_polling.is_circuit_open", lambda *_a, **_kw: _false_coro()
    )

    failing_result = {printer.ip_address: (PrinterStatus(is_online=False, status="offline"), None)}
    async def _fake_batch(*_a, **_kw):
        return failing_result

    monkeypatch.setattr("app.domains.inventory.printer_polling.poll_printer_batch", _fake_batch)

    # Cycle 1: first failure after being online - resilience should hold it
    # online for the grace period, and this cycle should learn nothing new
    # (no reason recorded) rather than declaring a cause for an offline
    # state that was never actually applied.
    await poll_all_printers_local(session=db_session, printer_type="laser")
    db_session.refresh(printer)
    assert printer.is_online is True
    assert printer.reachability_reason is None

    # Cycle 2: second consecutive failure - grace period exhausted.
    await poll_all_printers_local(session=db_session, printer_type="laser")
    db_session.refresh(printer)
    assert printer.is_online is False
    assert printer.reachability_reason == "no_response"


async def _false_coro():
    return False
