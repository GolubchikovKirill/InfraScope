from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from sqlmodel import select

from app.domains.inventory.cartridge_journal import detect_swaps, lifetime_stats, record_swaps
from app.domains.inventory.models import CartridgeReplacement, Printer
from app.domains.inventory.printer_polling import _apply_full_printer_result
from app.domains.ml.models import MLFeatureSnapshot
from app.services.ml_snapshots import write_printer_snapshots
from app.services.snmp import poller
from app.services.snmp.oids import PrinterStatus


def _printer(**levels) -> Printer:
    return Printer(
        printer_type="laser",
        connection_type="ip",
        store_name="ДФ Шереметьево D-12",
        model="HP M404",
        ip_address="10.12.0.21",
        toner_black_name="CF259A",
        **levels,
    )


def test_a_refill_sized_jump_is_a_swap_and_noise_is_not() -> None:
    swaps = detect_swaps(
        {"black": 6, "cyan": 40, "magenta": -3, "yellow": None},
        {"black": 98, "cyan": 48, "magenta": 100, "yellow": 100},
    )

    assert [(s.color, s.level_before, s.level_after) for s in swaps] == [("black", 6, 98)]


def test_the_second_swap_knows_how_long_the_cartridge_lasted(db_session) -> None:
    printer = _printer(toner_black=5)
    db_session.add(printer)
    db_session.commit()
    first_at = datetime(2026, 9, 1, tzinfo=UTC)

    (first,) = record_swaps(db_session, printer, detect_swaps({"black": 5}, {"black": 99}), page_count=10_000, now=first_at)
    db_session.commit()
    (second,) = record_swaps(
        db_session,
        printer,
        detect_swaps({"black": 3}, {"black": 97}),
        page_count=13_200,
        now=first_at + timedelta(days=40),
    )
    db_session.commit()

    assert first.lifetime_days is None and first.pages_printed is None
    assert second.lifetime_days == pytest.approx(40)
    assert second.pages_printed == 3_200
    assert second.cartridge_name == "CF259A"
    assert second.store_name == "ДФ Шереметьево D-12"


def test_a_full_poll_writes_the_journal_and_the_page_count(db_session) -> None:
    printer = _printer(toner_black=4)
    db_session.add(printer)
    db_session.commit()

    _apply_full_printer_result(
        printer,
        PrinterStatus(is_online=True, status="online", toner_black=100, page_count=52_345),
        None,
        session=db_session,
    )
    db_session.commit()

    (row,) = db_session.exec(select(CartridgeReplacement)).all()
    assert (row.level_before, row.level_after, row.page_count) == (4, 100, 52_345)
    assert printer.page_count == 52_345
    assert printer.page_count_updated_at is not None


def test_without_a_session_the_poll_result_is_applied_but_nothing_is_journalled(db_session) -> None:
    printer = _printer(toner_black=4)

    _apply_full_printer_result(printer, PrinterStatus(is_online=True, status="online", toner_black=100), None)

    assert printer.toner_black == 100
    assert db_session.exec(select(CartridgeReplacement)).all() == []


def test_the_page_count_reaches_the_ml_history(db_session) -> None:
    printer = _printer(toner_black=50)
    printer.page_count = 777
    db_session.add(printer)
    db_session.flush()

    write_printer_snapshots(db_session, printer)
    db_session.commit()

    counts = {s.toner_color: s.page_count for s in db_session.exec(select(MLFeatureSnapshot)).all()}
    assert counts[None] == 777


def test_lifetime_stats_take_the_median_per_cartridge() -> None:
    rows = [
        CartridgeReplacement(store_name="A", toner_color="black", cartridge_name="CF259A", level_before=3,
                             level_after=99, lifetime_days=days, pages_printed=pages)
        for days, pages in ((30, 3000), (40, 3400), (50, None))
    ]

    (stat,) = lifetime_stats(rows)

    assert stat.replacements == 3
    assert stat.median_lifetime_days == 40
    assert stat.median_pages == 3200


# The walk is replaced, so the engine/target/community are never touched
_NO_SNMP = cast(tuple[Any, Any, Any], (None, None, None))


@pytest.mark.asyncio
async def test_the_page_counter_takes_the_largest_marker_and_ignores_unsupported(monkeypatch) -> None:
    async def _walk(*_a):
        return [("1.3.6.1.2.1.43.10.2.1.4.1.1", "12345"), ("1.3.6.1.2.1.43.10.2.1.4.1.2", "900"), ("x", "n/a")]

    monkeypatch.setattr(poller, "_snmp_walk", _walk)
    assert await poller._read_page_count(*_NO_SNMP) == 12345

    async def _zero(*_a):
        return [("1.3.6.1.2.1.43.10.2.1.4.1.1", "0")]

    monkeypatch.setattr(poller, "_snmp_walk", _zero)
    assert await poller._read_page_count(*_NO_SNMP) is None


def test_the_journal_endpoint(client, user_token: str, db_session) -> None:
    printer = _printer(toner_black=5)
    db_session.add(printer)
    db_session.commit()
    record_swaps(db_session, printer, detect_swaps({"black": 5}, {"black": 99}), page_count=100)
    db_session.commit()

    response = client.get("/api/v1/printers/replacements", headers={"Authorization": f"Bearer {user_token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["data"][0]["cartridge_name"] == "CF259A"
    assert body["stats"][0]["replacements"] == 1
