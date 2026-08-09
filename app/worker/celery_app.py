from __future__ import annotations

from datetime import timedelta

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings
from app.worker import metrics_bootstrap  # noqa: F401

DEFAULT_QUEUE = "infrascope"

celery_app = Celery(
    "infrascope_worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_default_queue=DEFAULT_QUEUE,
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    result_expires=3600,
    broker_connection_retry_on_startup=True,
    task_soft_time_limit=300,
    task_time_limit=600,
    broker_transport_options={"visibility_timeout": settings.CELERY_VISIBILITY_TIMEOUT_SECONDS},
    result_backend_transport_options={"visibility_timeout": settings.CELERY_VISIBILITY_TIMEOUT_SECONDS},
)

_beat_schedule: dict = {}

# Backend-driven scheduled polling: replaces the old pattern of every open
# browser tab triggering a real device poll on its own timer. Each entity
# type runs every 15 minutes, offset from the others by a couple of minutes,
# so the network never sees a single all-at-once burst across every device
# type at :00. Toggle off entirely with AUTO_POLL_ENABLED=false.
if settings.AUTO_POLL_ENABLED:
    _beat_schedule.update(
        {
            "poll-printers-laser": {
                "task": "tasks.poll_all_printers",
                "schedule": crontab(minute="0,15,30,45"),
                "args": ("laser",),
            },
            "poll-printers-label": {
                "task": "tasks.poll_all_printers",
                "schedule": crontab(minute="2,17,32,47"),
                "args": ("label",),
            },
            "poll-media-players": {
                "task": "tasks.poll_all_media_players",
                "schedule": crontab(minute="4,19,34,49"),
                "args": (None,),
            },
            "poll-switches": {
                "task": "tasks.poll_all_switches",
                "schedule": crontab(minute="6,21,36,51"),
            },
            "poll-computers": {
                "task": "tasks.poll_all_computers",
                "schedule": crontab(minute="8,23,38,53"),
            },
            "poll-cash-registers": {
                "task": "tasks.poll_all_cash_registers",
                "schedule": crontab(minute="10,25,40,55"),
            },
        }
    )

if settings.AUTO_REBOOT_AP_ENABLED:
    # 07:30 and 19:30 Moscow time. Moscow is a fixed UTC+3 offset (no DST),
    # so this is just 04:30 and 16:30 UTC - no timezone library needed.
    _beat_schedule.update(
        {
            "ap-auto-reboot-morning": {
                "task": "tasks.ap_auto_reboot_cycle",
                "schedule": crontab(hour=4, minute=30),
            },
            "ap-auto-reboot-evening": {
                "task": "tasks.ap_auto_reboot_cycle",
                "schedule": crontab(hour=16, minute=30),
            },
        }
    )

if settings.SWITCH_PORT_SNAPSHOT_ENABLED:
    _beat_schedule.update(
        {
            "switch-port-snapshot": {
                "task": "tasks.switch_port_snapshot_cycle",
                "schedule": timedelta(days=settings.SWITCH_PORT_SNAPSHOT_INTERVAL_DAYS),
            },
        }
    )

celery_app.conf.beat_schedule = _beat_schedule
