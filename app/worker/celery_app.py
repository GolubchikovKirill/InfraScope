from __future__ import annotations

from celery import Celery

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
)
