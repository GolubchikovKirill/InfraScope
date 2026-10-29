from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from sqlmodel import select

from app.core.config import settings
from app.domains.integrations.models import HonestSignStatusRecord
from app.domains.integrations.schemas import HonestSignStatusPublic
from app.domains.operations.models import EventLog
from app.services import honest_sign


def _configure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "HONEST_SIGN_TARGETS", "172.23.8.21|Первая,172.23.8.36|XP касса")
    monkeypatch.setattr(settings, "HONEST_SIGN_API_LOGIN", "user")
    monkeypatch.setattr(settings, "HONEST_SIGN_API_PASSWORD", "password")
    monkeypatch.setattr(settings, "HONEST_SIGN_TOKEN", "00000000-0000-4000-8000-000000000001")
    monkeypatch.setattr(settings, "HONEST_SIGN_STATUS_WAIT_SECONDS", 0)


def test_configured_targets_normalizes_ipv4_and_labels() -> None:
    targets = honest_sign.configured_targets(
        "172.23.8.21|Первая|VNK-KKM-1501, "
        "172.23.8.21|Дубликат,invalid,172.23.8.36|Вторая|invalid_hostname!"
    )

    assert [(target.host, target.label, target.hostname) for target in targets] == [
        ("172.23.8.21", "Первая", "VNK-KKM-1501"),
        ("172.23.8.36", "Вторая", None),
    ]


@pytest.mark.asyncio
async def test_check_all_reports_ready_and_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "172.23.8.21":
            return httpx.Response(200, json={"status": "ready", "version": "2.5.1"})
        raise httpx.ConnectError("offline", request=request)

    monkeypatch.setattr(
        honest_sign,
        "_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=1),
    )

    rows = await honest_sign.check_all_honest_sign_targets()

    assert rows[0].ready is True
    assert rows[0].version == "2.5.1"
    assert rows[1].reachable is False
    assert rows[1].status == "ERROR"


@pytest.mark.asyncio
async def test_initialize_skips_module_that_is_already_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(200, json={"status": "ready", "version": "2.5.1"})

    monkeypatch.setattr(
        honest_sign,
        "_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=1),
    )

    result = await honest_sign.initialize_honest_sign_target(honest_sign.configured_targets()[0])

    assert result.result == "ALREADY_READY"
    assert methods == ["GET"]


def test_ip_override_redirects_target_and_is_stable_across_edits(monkeypatch, db_session) -> None:
    monkeypatch.setattr(settings, "HONEST_SIGN_TARGETS", "172.23.8.21|A15|VNK-KKM-1501")

    updated = honest_sign.set_target_ip_override(db_session, "172.23.8.21", "172.23.8.6")
    assert updated.host == "172.23.8.6"
    assert updated.original_host == "172.23.8.21"

    targets = honest_sign.configured_targets(session=db_session)
    assert [(t.original_host, t.host) for t in targets] == [("172.23.8.21", "172.23.8.6")]

    # Re-editing the same target is keyed by the original host, not the
    # previous override.
    updated_again = honest_sign.set_target_ip_override(db_session, "172.23.8.21", "172.23.8.7")
    assert updated_again.host == "172.23.8.7"
    targets_again = honest_sign.configured_targets(session=db_session)
    assert [(t.original_host, t.host) for t in targets_again] == [("172.23.8.21", "172.23.8.7")]


def test_ip_override_rejects_unknown_target(monkeypatch, db_session) -> None:
    monkeypatch.setattr(settings, "HONEST_SIGN_TARGETS", "172.23.8.21|A15")

    with pytest.raises(KeyError):
        honest_sign.set_target_ip_override(db_session, "10.0.0.99", "172.23.8.6")


def test_ip_override_rejects_collision_with_another_target(monkeypatch, db_session) -> None:
    monkeypatch.setattr(settings, "HONEST_SIGN_TARGETS", "172.23.8.21|A15,172.23.8.36|A16")

    with pytest.raises(ValueError):
        honest_sign.set_target_ip_override(db_session, "172.23.8.21", "172.23.8.36")


def _row(original_host="172.23.8.21", *, host=None, ready=True, reachable=True, status=None, minute=0):
    return HonestSignStatusPublic(
        host=host or original_host,
        label="A15",
        original_host=original_host,
        reachable=reachable,
        status=status or ("ready" if ready else "ERROR" if not reachable else "not_initialized"),
        ready=ready,
        message="" if reachable else "Нет соединения с Local Module",
        checked_at=datetime(2026, 10, 29, 10, minute, tzinfo=UTC).isoformat(),
    )


def _events(db_session) -> list[str]:
    return [e.event_type for e in db_session.exec(select(EventLog).order_by(EventLog.created_at)).all()]


def test_record_results_alerts_once_after_threshold_and_logs_recovery(monkeypatch, db_session) -> None:
    monkeypatch.setattr(settings, "HONEST_SIGN_ALERT_AFTER_FAILURES", 2)

    honest_sign.record_check_results(db_session, [_row(ready=False, reachable=False, minute=0)])
    assert _events(db_session) == []  # one miss is still a blip

    honest_sign.record_check_results(db_session, [_row(ready=False, reachable=False, minute=15)])
    honest_sign.record_check_results(db_session, [_row(ready=False, reachable=False, minute=30)])
    assert _events(db_session) == ["honest_sign_down"]  # reported once, not every cycle

    honest_sign.record_check_results(db_session, [_row(ready=True, minute=45)])
    assert _events(db_session) == ["honest_sign_down", "honest_sign_recovered"]

    record = db_session.exec(select(HonestSignStatusRecord)).one()
    assert record.consecutive_failures == 0
    assert record.problem_reported is False


def test_record_results_reports_reachable_but_not_ready_as_warning(monkeypatch, db_session) -> None:
    monkeypatch.setattr(settings, "HONEST_SIGN_ALERT_AFTER_FAILURES", 1)

    honest_sign.record_check_results(db_session, [_row(ready=False, minute=0)])

    event = db_session.exec(select(EventLog)).one()
    assert (event.event_type, event.severity, event.device_name, event.ip_address) == (
        "honest_sign_not_ready",
        "warning",
        "A15",
        "172.23.8.21",
    )


def test_record_results_does_not_alert_a_register_that_never_failed(monkeypatch, db_session) -> None:
    monkeypatch.setattr(settings, "HONEST_SIGN_ALERT_AFTER_FAILURES", 1)

    honest_sign.record_check_results(db_session, [_row(ready=True, minute=0)])
    honest_sign.record_check_results(db_session, [_row(ready=True, minute=15)])

    assert _events(db_session) == []


def test_record_results_tracks_state_since_only_on_change(db_session) -> None:
    honest_sign.record_check_results(db_session, [_row(ready=True, minute=0)])
    honest_sign.record_check_results(db_session, [_row(ready=True, minute=15)])
    honest_sign.record_check_results(db_session, [_row(ready=False, reachable=False, minute=30)])

    record = db_session.exec(select(HonestSignStatusRecord)).one()
    assert record.state_since.minute == 30
    assert record.checked_at.minute == 30


def test_record_results_resets_streak_when_register_moves_to_another_ip(monkeypatch, db_session) -> None:
    monkeypatch.setattr(settings, "HONEST_SIGN_ALERT_AFTER_FAILURES", 2)
    honest_sign.record_check_results(db_session, [_row(ready=False, reachable=False, minute=0)])

    # Second failure, but against a new IP: the old IP's streak must not count.
    honest_sign.record_check_results(
        db_session, [_row(host="172.23.8.6", ready=False, reachable=False, minute=15)]
    )

    assert _events(db_session) == []
    assert db_session.exec(select(HonestSignStatusRecord)).one().consecutive_failures == 1


def test_record_results_drops_registers_that_are_no_longer_configured(db_session) -> None:
    honest_sign.record_check_results(db_session, [_row("172.23.8.21"), _row("172.23.8.36")])
    honest_sign.record_check_results(db_session, [_row("172.23.8.21")])

    assert [r.original_host for r in db_session.exec(select(HonestSignStatusRecord)).all()] == ["172.23.8.21"]


def test_stored_statuses_follow_configured_targets_and_skip_stale_ip(monkeypatch, db_session) -> None:
    monkeypatch.setattr(settings, "HONEST_SIGN_TARGETS", "172.23.8.21|A15|VNK-KKM-1501,172.23.8.36|A16")
    honest_sign.record_check_results(db_session, [_row("172.23.8.21", minute=5)])

    rows = honest_sign.stored_statuses(db_session)
    assert [(r.host, r.hostname, r.ready, r.consecutive_failures) for r in rows] == [
        ("172.23.8.21", "VNK-KKM-1501", True, 0)
    ]
    assert rows[0].checked_at == "2026-10-29T10:05:00+00:00"

    honest_sign.set_target_ip_override(db_session, "172.23.8.21", "172.23.8.6")
    assert honest_sign.stored_statuses(db_session) == []  # the stored status was for the old IP
