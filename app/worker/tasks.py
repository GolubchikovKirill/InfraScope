from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from time import perf_counter
from urllib.parse import urlparse

import httpx
from celery import shared_task
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.domains.inventory.models import MediaPlayer, NetworkSwitch, Printer
from app.observability.metrics import (
    observe_service_edge,
    worker_task_duration_seconds,
    worker_task_executions_total,
    worker_tasks_in_progress,
)
from app.services.polling_orchestrator import (
    poll_all_media_players_local,
    poll_all_printers_local,
    poll_switch_local,
)
from app.services.scanner import scan_subnet


def _task_started(operation: str) -> float:
    worker_tasks_in_progress.labels(operation=operation).inc()
    return perf_counter()


def _task_finished(operation: str, started_at: float, result: str) -> None:
    worker_tasks_in_progress.labels(operation=operation).dec()
    worker_task_executions_total.labels(operation=operation, result=result).inc()
    worker_task_duration_seconds.labels(operation=operation).observe(max(perf_counter() - started_at, 0))


def _internal_headers() -> dict[str, str]:
    if settings.INTERNAL_SERVICE_TOKEN:
        return {"X-Internal-Token": settings.INTERNAL_SERVICE_TOKEN}
    return {}


def _service_json(
    *,
    base_url: str,
    method: str,
    path: str,
    timeout: float = 180.0,
    params: dict | None = None,
    json_body: dict | None = None,
) -> dict:
    target = (urlparse(base_url).hostname or "unknown").strip() or "unknown"
    with observe_service_edge(
        source="worker",
        target=target,
        transport="http",
        operation=f"{method.upper()} {path}",
    ):
        with httpx.Client(timeout=timeout, headers=_internal_headers()) as client:
            response = client.request(
                method=method,
                url=f"{base_url.rstrip('/')}{path}",
                params=params,
                json=json_body,
            )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("internal service returned invalid payload")
    return data


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    name="tasks.scan_network",
)
def scan_network_task(self, subnet: str, ports: str) -> dict:
    operation = "scan_network"
    started_at = _task_started(operation)
    try:
        with Session(engine) as session:
            printers = session.exec(select(Printer)).all()
            known = [
                {
                    "id": str(p.id),
                    "ip_address": p.ip_address,
                    "mac_address": p.mac_address,
                    "store_name": p.store_name,
                }
                for p in printers
            ]
        if settings.DISCOVERY_SERVICE_ENABLED:
            payload_data = _service_json(
                base_url=settings.DISCOVERY_SERVICE_URL,
                method="POST",
                path="/discover/printers/run",
                json_body={
                    "subnet": subnet,
                    "ports": ports,
                    "known_printers": known,
                },
            )
            devices = payload_data.get("devices", [])
        else:
            devices = asyncio.run(scan_subnet(subnet, ports, known))
        payload = {
            "task_id": self.request.id,
            "operation": operation,
            "subnet": subnet,
            "ports": ports,
            "found_devices": len(devices),
        }
        _task_finished(operation, started_at, "success")
        return payload
    except Exception:
        _task_finished(operation, started_at, "error")
        raise


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
    name="tasks.poll_all_printers",
)
def poll_all_printers_task(self, printer_type: str = "laser") -> dict:
    operation = "poll_all_printers"
    started_at = _task_started(operation)
    try:
        if settings.POLLING_SERVICE_ENABLED:
            payload_data = _service_json(
                base_url=settings.POLLING_SERVICE_URL,
                method="POST",
                path="/poll/printers",
                params={"printer_type": printer_type},
            )
            all_printers = payload_data.get("data", [])
            online_count = sum(1 for p in all_printers if p.get("is_online"))
            total_count = len(all_printers)
        else:
            with Session(engine) as session:
                asyncio.run(poll_all_printers_local(session=session, printer_type=printer_type))
                all_printers = session.exec(select(Printer).where(Printer.printer_type == printer_type)).all()
            online_count = sum(1 for p in all_printers if p.is_online)
            total_count = len(all_printers)
        payload = {
            "task_id": self.request.id,
            "operation": operation,
            "printer_type": printer_type,
            "total": total_count,
            "online": online_count,
            "finished_at": datetime.now(UTC).isoformat(),
        }
        _task_finished(operation, started_at, "success")
        return payload
    except Exception:
        _task_finished(operation, started_at, "error")
        raise


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
    name="tasks.poll_all_media_players",
)
def poll_all_media_players_task(self, device_type: str | None = None) -> dict:
    operation = "poll_all_media_players"
    started_at = _task_started(operation)
    try:
        if settings.POLLING_SERVICE_ENABLED:
            payload_data = _service_json(
                base_url=settings.POLLING_SERVICE_URL,
                method="POST",
                path="/poll/media-players",
                params={"device_type": device_type} if device_type else None,
            )
            players = payload_data.get("data", [])
            total_count = len(players)
            online_count = sum(1 for p in players if p.get("is_online"))
        else:
            with Session(engine) as session:
                asyncio.run(
                    poll_all_media_players_local(
                        session=session,
                        device_type=device_type,
                    )
                )
                statement = select(MediaPlayer)
                if device_type:
                    statement = statement.where(MediaPlayer.device_type == device_type)
                players = session.exec(statement).all()
            total_count = len(players)
            online_count = sum(1 for p in players if p.is_online)
        payload = {
            "task_id": self.request.id,
            "operation": operation,
            "device_type": device_type,
            "total": total_count,
            "online": online_count,
            "finished_at": datetime.now(UTC).isoformat(),
        }
        _task_finished(operation, started_at, "success")
        return payload
    except Exception:
        _task_finished(operation, started_at, "error")
        raise


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
    name="tasks.poll_switch",
)
def poll_switch_task(self, switch_id: str) -> dict:
    operation = "poll_switch"
    started_at = _task_started(operation)
    try:
        switch_uuid = uuid.UUID(switch_id)
        if settings.POLLING_SERVICE_ENABLED:
            sw = _service_json(
                base_url=settings.POLLING_SERVICE_URL,
                method="POST",
                path=f"/poll/switches/{switch_id}",
            )
            is_online = bool(sw.get("is_online"))
            hostname = sw.get("hostname")
        else:
            with Session(engine) as session:
                sw = asyncio.run(poll_switch_local(switch_id=switch_uuid, session=session))
            is_online = bool(sw.is_online)
            hostname = sw.hostname
        payload = {
            "task_id": self.request.id,
            "operation": operation,
            "switch_id": switch_id,
            "is_online": is_online,
            "hostname": hostname,
            "finished_at": datetime.now(UTC).isoformat(),
        }
        _task_finished(operation, started_at, "success")
        return payload
    except Exception:
        _task_finished(operation, started_at, "error")
        raise


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
    name="tasks.poll_all_switches",
)
def poll_all_switches_task(self) -> dict:
    operation = "poll_all_switches"
    started_at = _task_started(operation)
    try:
        results: list[dict] = []
        if settings.POLLING_SERVICE_ENABLED:
            _service_json(
                base_url=settings.POLLING_SERVICE_URL,
                method="POST",
                path="/poll/switches",
            )
            summary = _service_json(
                base_url=settings.POLLING_SERVICE_URL,
                method="GET",
                path="/summary/switches",
            )
            total = int(summary.get("total", 0))
            online = int(summary.get("online", 0))
        else:
            with Session(engine) as session:
                switches = session.exec(select(NetworkSwitch)).all()
                for sw in switches:
                    updated = asyncio.run(poll_switch_local(switch_id=sw.id, session=session))
                    results.append(
                        {
                            "switch_id": str(updated.id),
                            "name": updated.name,
                            "is_online": bool(updated.is_online),
                        }
                    )
            total = len(results)
            online = sum(1 for r in results if r["is_online"])
        payload = {
            "task_id": self.request.id,
            "operation": operation,
            "total": total,
            "online": online,
            "switches": results,
            "finished_at": datetime.now(UTC).isoformat(),
        }
        _task_finished(operation, started_at, "success")
        return payload
    except Exception:
        _task_finished(operation, started_at, "error")
        raise


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
    name="tasks.ml_run_cycle",
)
def ml_run_cycle_task(self) -> dict:
    operation = "ml_run_cycle"
    started_at = _task_started(operation)
    if not settings.ML_ENABLED:
        _task_finished(operation, started_at, "skipped")
        return {
            "task_id": self.request.id,
            "operation": operation,
            "status": "skipped",
            "reason": "ml_disabled",
        }
    try:
        with httpx.Client(timeout=180) as client:
            response = client.post(f"{settings.ML_SERVICE_URL.rstrip('/')}/run-cycle")
        response.raise_for_status()
        payload = {
            "task_id": self.request.id,
            "operation": operation,
            "result": response.json(),
            "finished_at": datetime.now(UTC).isoformat(),
        }
        _task_finished(operation, started_at, "success")
        return payload
    except Exception:
        _task_finished(operation, started_at, "error")
        raise
