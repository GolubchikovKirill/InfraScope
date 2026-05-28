from __future__ import annotations

import os

from celery.signals import worker_ready
from prometheus_client import start_http_server

_started = False


@worker_ready.connect
def start_worker_metrics_server(**_kwargs) -> None:
    global _started
    if _started:
        return
    port = int(os.getenv("WORKER_METRICS_PORT", "9108"))
    start_http_server(port)
    _started = True
