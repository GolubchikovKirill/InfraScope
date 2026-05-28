from __future__ import annotations

from app.domains.operations.cash_register_polling import (
    apply_cash_register_poll_result,
    cash_register_offline_reason_ru,
    record_cash_register_status_change,
)
from app.domains.operations.models import CashRegister


def test_apply_cash_register_poll_result_updates_reachability_fields() -> None:
    cash = CashRegister(kkm_number="001", hostname="cash-a1")

    apply_cash_register_poll_result(cash, is_online=False, reason="dns_unresolved")

    assert cash.is_online is False
    assert cash.reachability_reason == "dns_unresolved"
    assert cash.last_polled_at is not None


def test_cash_register_offline_reason_ru_has_stable_user_text() -> None:
    assert cash_register_offline_reason_ru("dns_unresolved") == "hostname не резолвится"
    assert cash_register_offline_reason_ru("port_closed") == "сетевые порты недоступны"
    assert cash_register_offline_reason_ru("other") == "хост недоступен"
    assert cash_register_offline_reason_ru(None) == "хост недоступен"


def test_record_cash_register_status_change_skips_unchanged_state(monkeypatch) -> None:
    cash = CashRegister(kkm_number="001", hostname="cash-a1", is_online=True)

    def should_not_write(*_args, **_kwargs) -> None:
        raise AssertionError("event log should not be written when status did not change")

    monkeypatch.setattr("app.domains.operations.cash_register_polling.write_event_log", should_not_write)

    record_cash_register_status_change(None, cash, True)


def test_record_cash_register_status_change_writes_offline_event(monkeypatch) -> None:
    cash = CashRegister(
        kkm_number="001",
        hostname="cash-a1",
        is_online=False,
        reachability_reason="port_closed",
    )
    captured = {}

    def fake_write_event_log(_session, **kwargs) -> None:
        captured.update(kwargs)

    monkeypatch.setattr("app.domains.operations.cash_register_polling.write_event_log", fake_write_event_log)

    record_cash_register_status_change(None, cash, True)

    assert captured["event_type"] == "cash_register_offline"
    assert captured["severity"] == "warning"
    assert "сетевые порты недоступны" in captured["message"]
