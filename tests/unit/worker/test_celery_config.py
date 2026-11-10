from app.core.config import settings
from app.worker.celery_app import DEFAULT_QUEUE, celery_app


def test_celery_uses_redis_for_broker_and_backend():
    assert str(celery_app.conf.broker_url).startswith("redis://")
    assert str(celery_app.conf.result_backend).startswith("redis://")


def test_celery_has_production_safety_defaults():
    assert celery_app.conf.task_default_queue == DEFAULT_QUEUE
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.worker_prefetch_multiplier == 1
    assert celery_app.conf.task_time_limit >= celery_app.conf.task_soft_time_limit
    assert celery_app.conf.broker_transport_options["visibility_timeout"] >= 10_800
    assert celery_app.conf.result_backend_transport_options["visibility_timeout"] >= 10_800


def test_availability_and_toner_have_separate_expiring_schedules():
    schedule = celery_app.conf.beat_schedule
    light = schedule["poll-printers-laser"]
    full = schedule["poll-printer-telemetry"]
    assert light["kwargs"] == {"full": False}
    assert full["kwargs"] == {"full": True}
    assert light["schedule"].total_seconds() == settings.AUTO_POLL_INTERVAL_SECONDS
    assert full["schedule"].total_seconds() == settings.PRINTER_TELEMETRY_INTERVAL_SECONDS
    for key in ("poll-printers-laser", "poll-printers-label", "poll-media-players", "poll-switches", "poll-computers", "poll-cash-registers", "poll-printer-telemetry"):
        assert schedule[key]["options"]["queue"] == "polling"
        assert schedule[key]["options"]["expires"] > 0
    assert celery_app.conf.task_routes["tasks.poll_all_printers"]["queue"] == "polling"
