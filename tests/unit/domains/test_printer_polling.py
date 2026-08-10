from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.domains.inventory.models import Printer
from app.domains.inventory.printer_polling import (
    _apply_full_printer_result,
    _apply_light_printer_result,
    _subnets_with_total_failure,
    is_full_poll_cycle,
    poll_one_printer,
    poll_printer_batch,
    poll_single_printer_local,
    verify_printer_mac,
)
from app.services.snmp import PrinterStatus


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


def test_poll_printer_batch_preserves_result_for_each_ip(monkeypatch) -> None:
    printers = [
        Printer(
            printer_type="label",
            connection_type="ip",
            store_name="Label A",
            model="Zebra",
            ip_address="10.10.10.20",
        ),
        Printer(
            printer_type="label",
            connection_type="ip",
            store_name="Label B",
            model="Zebra",
            ip_address="10.10.10.21",
        ),
    ]

    def fake_poll_one(printer: Printer, *, full: bool = True):
        del full
        return printer.ip_address, {"is_online": printer.ip_address.endswith(".20")}, None

    monkeypatch.setattr("app.domains.inventory.printer_polling.poll_one_printer", fake_poll_one)

    result = poll_printer_batch(printers)

    assert result == {
        "10.10.10.20": ({"is_online": True}, None),
        "10.10.10.21": ({"is_online": False}, None),
    }


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


def test_poll_one_printer_light_skips_toner_and_mac_calls(monkeypatch) -> None:
    printer = Printer(
        printer_type="laser",
        connection_type="ip",
        store_name="Store A",
        model="HP",
        ip_address="10.10.10.30",
    )
    monkeypatch.setattr(
        "app.domains.inventory.printer_polling.poll_printer_light",
        lambda ip, community: PrinterStatus(is_online=True, status="online"),
    )

    def _must_not_be_called(*_a, **_kw):
        raise AssertionError("full poll and MAC lookup must not run on a light cycle")

    monkeypatch.setattr("app.domains.inventory.printer_polling.poll_printer", _must_not_be_called)
    monkeypatch.setattr("app.domains.inventory.printer_polling.get_snmp_mac", _must_not_be_called)

    ip, result, mac = poll_one_printer(printer, full=False)

    assert ip == "10.10.10.30"
    assert result.is_online is True
    assert mac is None


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

    results = {
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
        "10.10.98.11": ({"is_online": True}, None),
        "10.10.98.12": ({"is_online": True}, None),
        "10.10.98.13": ({"is_online": True}, None),
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
        "10.10.99.10": ({"is_online": True}, None),
        "10.10.99.11": ({"is_online": True}, None),
        "10.10.99.12": ({"is_online": True}, None),
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

    def flaky_poll_one(target_printer: Printer, *, full: bool = True):
        del full
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

    def always_fails(target_printer: Printer, *, full: bool = True):
        del full
        calls["count"] += 1
        return target_printer.ip_address, None, None

    monkeypatch.setattr("app.domains.inventory.printer_polling.poll_one_printer", always_fails)

    result = await poll_single_printer_local(session=db_session, printer_id=printer.id)

    assert calls["count"] == 2
    assert result.is_online is False
    assert result.status == "error"
