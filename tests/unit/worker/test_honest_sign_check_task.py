from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlmodel import select

from app.core.config import settings
from app.domains.integrations.models import HonestSignStatusRecord
from app.domains.integrations.schemas import HonestSignStatusPublic
from app.services import honest_sign
from app.worker import tasks


def _result(original_host: str, *, ready: bool, reachable: bool = True) -> HonestSignStatusPublic:
    return HonestSignStatusPublic(
        host=original_host,
        label="A15",
        original_host=original_host,
        reachable=reachable,
        status="ready" if ready else "ERROR" if not reachable else "not_initialized",
        ready=ready,
        checked_at=datetime.now(UTC).isoformat(),
    )


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "HONEST_SIGN_TARGETS", "172.23.8.21|A15,172.23.8.36|A16,172.23.8.37|A17")
    monkeypatch.setattr(settings, "HONEST_SIGN_API_LOGIN", "user")
    monkeypatch.setattr(settings, "HONEST_SIGN_API_PASSWORD", "password")
    monkeypatch.setattr(settings, "HONEST_SIGN_AUTO_CHECK_ENABLED", True)


def test_check_cycle_stores_results_and_never_initializes(monkeypatch, db_session, configured):
    async def fake_check_all(session=None):
        return [
            _result("172.23.8.21", ready=True),
            _result("172.23.8.36", ready=False),
            _result("172.23.8.37", ready=False, reachable=False),
        ]

    async def forbidden_init(*_a, **_kw):
        raise AssertionError("the scheduled check must not activate a Local Module")

    monkeypatch.setattr(honest_sign, "check_all_honest_sign_targets", fake_check_all)
    monkeypatch.setattr(honest_sign, "initialize_honest_sign_target", forbidden_init)
    monkeypatch.setattr(tasks, "engine", db_session.get_bind())

    result = tasks.honest_sign_check_cycle_task.run()

    assert (result["total"], result["ready"], result["not_ready"], result["unreachable"]) == (3, 1, 1, 1)
    stored = {r.original_host: r.ready for r in db_session.exec(select(HonestSignStatusRecord)).all()}
    assert stored == {"172.23.8.21": True, "172.23.8.36": False, "172.23.8.37": False}


@pytest.mark.parametrize("enabled", [False, True])
def test_check_cycle_is_skipped_when_off_or_not_configured(monkeypatch, db_session, configured, enabled):
    monkeypatch.setattr(settings, "HONEST_SIGN_AUTO_CHECK_ENABLED", enabled)
    monkeypatch.setattr(settings, "HONEST_SIGN_TARGETS", "" if enabled else settings.HONEST_SIGN_TARGETS)
    monkeypatch.setattr(tasks, "engine", db_session.get_bind())

    async def forbidden(*_a, **_kw):
        raise AssertionError("must not contact any register")

    monkeypatch.setattr(honest_sign, "check_all_honest_sign_targets", forbidden)

    assert tasks.honest_sign_check_cycle_task.run()["status"] == "skipped"


def test_beat_schedules_the_check_with_the_configured_interval():
    import importlib

    from app.worker import celery_app as celery_module

    original = (settings.HONEST_SIGN_AUTO_CHECK_ENABLED, settings.HONEST_SIGN_AUTO_CHECK_INTERVAL_MINUTES)
    try:
        settings.HONEST_SIGN_AUTO_CHECK_ENABLED = True
        settings.HONEST_SIGN_AUTO_CHECK_INTERVAL_MINUTES = 7
        reloaded = importlib.reload(celery_module)
        entry = reloaded.celery_app.conf.beat_schedule["honest-sign-check"]
        assert entry["task"] == "tasks.honest_sign_check_cycle"
        assert entry["schedule"].total_seconds() == 7 * 60

        settings.HONEST_SIGN_AUTO_CHECK_ENABLED = False
        reloaded = importlib.reload(celery_module)
        assert "honest-sign-check" not in reloaded.celery_app.conf.beat_schedule
    finally:
        settings.HONEST_SIGN_AUTO_CHECK_ENABLED, settings.HONEST_SIGN_AUTO_CHECK_INTERVAL_MINUTES = original
        importlib.reload(celery_module)
