from __future__ import annotations

import pytest
import redis

from app.core.config import settings
from app.worker import tasks
from app.worker.celery_app import celery_app


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the three pipeline stages with recorders."""
    order: list[str] = []
    monkeypatch.setattr(settings, "ML_ENABLED", True)
    monkeypatch.setattr(tasks, "run_training_cycle", lambda _s, **_kw: order.append("train") or {"toner": "v1"})
    monkeypatch.setattr(tasks, "run_scoring_cycle", lambda _s: order.append("score") or {"toner_predictions": 3})
    monkeypatch.setattr(
        tasks,
        "run_retention_cycle",
        lambda _s, **_kw: order.append("retention") or {"feature_snapshots_deleted": 5},
    )
    return order


def _lock_present() -> bool:
    client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return client.get(tasks._ML_LOCK_KEY) is not None


def test_daily_cycle_trains_scores_then_prunes_in_that_order(calls):
    result = tasks.ml_daily_cycle_task.run()

    assert calls == ["train", "score", "retention"]
    assert result["operation"] == "ml_daily_cycle"
    assert result["result"]["retention"] == {"feature_snapshots_deleted": 5}


def test_manual_cycle_trains_and_scores_but_does_not_prune(calls):
    tasks.ml_run_cycle_task.run()

    assert calls == ["train", "score"]


def test_score_cycle_never_trains_or_prunes(calls):
    tasks.ml_score_cycle_task.run()

    assert calls == ["score"]


def test_disabled_ml_is_a_noop(calls, monkeypatch):
    monkeypatch.setattr(settings, "ML_ENABLED", False)

    result = tasks.ml_daily_cycle_task.run()

    assert result["status"] == "skipped"
    assert result["reason"] == "ml_disabled"
    assert calls == []


def test_a_second_cycle_is_skipped_while_one_holds_the_lock(calls):
    client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    client.set(tasks._ML_LOCK_KEY, "someone-else", ex=60)

    result = tasks.ml_score_cycle_task.run()

    assert result["status"] == "skipped"
    assert result["reason"] == "another_ml_cycle_running"
    assert calls == []
    # and it must not steal or clear the other holder's lock
    assert client.get(tasks._ML_LOCK_KEY) == "someone-else"


def test_lock_is_released_after_a_successful_cycle(calls):
    tasks.ml_score_cycle_task.run()

    assert not _lock_present()


def test_lock_is_released_and_error_propagates_when_training_fails(calls, monkeypatch):
    def _boom(_session, **_kwargs):
        raise RuntimeError("training exploded")

    monkeypatch.setattr(tasks, "run_training_cycle", _boom)

    with pytest.raises(RuntimeError, match="training exploded"):
        tasks.ml_daily_cycle_task.run()

    assert not _lock_present()
    assert "score" not in calls and "retention" not in calls


def test_cycle_still_runs_when_redis_is_unreachable(calls, monkeypatch):
    # ML touches no hardware: a Redis blip must not stop forecasting.
    class _Broken:
        def set(self, *_a, **_kw):
            raise redis.exceptions.ConnectionError("down")

        def close(self):
            pass

    monkeypatch.setattr(redis.Redis, "from_url", classmethod(lambda cls, *_a, **_kw: _Broken()))

    tasks.ml_score_cycle_task.run()

    assert calls == ["score"]


def test_beat_schedules_the_daily_and_the_scoring_cycle():
    schedule = celery_app.conf.beat_schedule

    assert schedule["ml-daily-cycle"]["task"] == "tasks.ml_daily_cycle"
    assert schedule["ml-score-cycle"]["task"] == "tasks.ml_score_cycle"
    daily = schedule["ml-daily-cycle"]["schedule"]
    assert daily.hour == {settings.ML_RETRAIN_HOUR_UTC}
    assert daily.minute == {0}
    assert schedule["ml-score-cycle"]["schedule"].total_seconds() == settings.ML_SCORE_INTERVAL_MINUTES * 60
