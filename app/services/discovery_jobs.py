"""Queueing of network discovery scans.

These used to run inside the discovery-service container (or, in the API's
"local" mode, as a fire-and-forget task on the API's own event loop). They now
run as Celery tasks in the worker: a scan is minutes of socket and SNMP work,
which the API process should not share with request handling.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.services import discovery, scanner
from app.worker.tasks import discovery_scan_task

SCAN_KINDS = ("printers", "iconbit", "switch")

_RUNNING = {"status": "running", "scanned": 0, "total": 0, "found": 0, "message": None}


async def enqueue_scan(kind: str, subnet: str, ports: str, known: list[dict[str, Any]]) -> dict[str, Any]:
    """Queue a scan and answer with the "running" progress the UI expects.

    409 while a scan of the same kind is still running - the same answer the
    discovery service gave. The scan functions also take that Redis lock
    themselves, so a race between two requests still ends with one scan.
    """
    if kind not in SCAN_KINDS:
        raise HTTPException(status_code=422, detail="unsupported discovery kind")

    busy = await scanner.scan_in_progress() if kind == "printers" else await discovery.discovery_in_progress(kind)
    if busy:
        raise HTTPException(status_code=409, detail=f"{kind} discovery already in progress")

    if kind == "printers":
        await scanner.mark_scan_queued()
    else:
        await discovery.mark_discovery_queued(kind)

    try:
        discovery_scan_task.delay(kind, subnet, ports, known)
    except Exception as exc:
        message = f"Task queue unavailable: {exc}"
        if kind == "printers":
            await scanner.mark_scan_failed_to_queue(message)
        else:
            await discovery.mark_discovery_failed_to_queue(kind, message)
        raise HTTPException(status_code=503, detail=message) from exc

    return dict(_RUNNING)
