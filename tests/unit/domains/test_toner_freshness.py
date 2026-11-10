from datetime import UTC, datetime

import pytest
from sqlmodel import select

from app.domains.inventory.models import Printer
from app.domains.inventory.printer_polling import _apply_full_printer_result
from app.domains.ml.models import MLFeatureSnapshot
from app.services.ml_snapshots import write_printer_snapshots
from app.services.snmp import PrinterStatus, toner_strategies


def test_partial_and_unknown_responses_preserve_measurements():
    old = datetime(2026, 1, 1, tzinfo=UTC)
    printer = Printer(store_name="A", model="HP", toner_black=42, toner_cyan=60,
                      toner_updated_at=old, toner_observed_at={"black": old.isoformat(), "cyan": old.isoformat()})
    _apply_full_printer_result(printer, PrinterStatus(is_online=True, status="online", toner_black=0), None)
    assert printer.toner_black == 0
    assert printer.toner_cyan == 60
    assert printer.toner_observed_at["cyan"] == old.isoformat()
    assert printer.toner_updated_at == old
    black_time = printer.toner_observed_at["black"]
    _apply_full_printer_result(printer, PrinterStatus(is_online=True, status="online", toner_black=-2), None)
    assert printer.toner_black == 0
    assert printer.toner_observed_at["black"] == black_time


def test_history_does_not_repeat_cached_toner(db_session):
    printer = Printer(store_name="A", model="HP")
    db_session.add(printer)
    _apply_full_printer_result(printer, PrinterStatus(is_online=True, status="online", toner_black=42), None)
    write_printer_snapshots(db_session, printer)
    db_session.flush()
    write_printer_snapshots(db_session, printer)
    db_session.flush()
    rows = db_session.exec(select(MLFeatureSnapshot).where(MLFeatureSnapshot.toner_color == "black")).all()
    assert len(rows) == 1
    assert rows[0].toner_level == 42


@pytest.mark.asyncio
async def test_missing_supply_level_is_unknown_not_empty(monkeypatch):
    async def walk(_engine, _target, _community, oid):
        if oid == toner_strategies.OID_MARKER_DESCR:
            return [(f"{oid}.1.1", "Black toner"), (f"{oid}.1.2", "Cyan toner")]
        if oid == toner_strategies.OID_MARKER_MAX:
            return [(f"{oid}.1.1", "100"), (f"{oid}.1.2", "100")]
        if oid == toner_strategies.OID_MARKER_LEVEL:
            return [(f"{oid}.1.1", "0")]
        return []

    monkeypatch.setattr(toner_strategies, "_snmp_walk", walk)
    levels = await toner_strategies._get_standard_toners(None, None, None)
    assert {row.color: row.level_pct for row in levels} == {"black": 0, "cyan": -2}
