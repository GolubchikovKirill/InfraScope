from __future__ import annotations

from typing import Any

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, get_current_active_superuser
from app.observability.metrics import worker_task_status_checks_total, worker_tasks_enqueued_total
from app.worker.celery_app import celery_app
from app.worker.tasks import (
    ml_run_cycle_task,
    poll_all_media_players_task,
    poll_all_printers_task,
    poll_all_switches_task,
    poll_switch_task,
    scan_network_task,
)

router = APIRouter(tags=["tasks"])


class TaskEnqueueResponse(BaseModel):
    task_id: str
    state: str
    operation: str


class TaskStatusResponse(BaseModel):
    task_id: str
    state: str
    ready: bool
    successful: bool | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class ScanTaskRequest(BaseModel):
    subnet: str = Field(min_length=3, max_length=512)
    ports: str = Field(default="9100,631,80,443", min_length=1, max_length=128)


class PrinterPollTaskRequest(BaseModel):
    printer_type: str = Field(default="laser", pattern="^(laser|label)$")


class MediaPollTaskRequest(BaseModel):
    device_type: str | None = Field(default=None, pattern="^(nettop|iconbit|twix)$")


class SwitchPollTaskRequest(BaseModel):
    switch_id: str


class MLCycleTaskRequest(BaseModel):
    force: bool = False


@router.post(
    "/scan-network",
    response_model=TaskEnqueueResponse,
    dependencies=[Depends(get_current_active_superuser)],
)
def enqueue_scan_network(body: ScanTaskRequest) -> TaskEnqueueResponse:
    task = scan_network_task.delay(body.subnet, body.ports)
    worker_tasks_enqueued_total.labels(operation="scan_network").inc()
    return TaskEnqueueResponse(task_id=task.id, state=task.state, operation="scan_network")


@router.post("/poll-printers", response_model=TaskEnqueueResponse)
def enqueue_poll_printers(body: PrinterPollTaskRequest, current_user: CurrentUser) -> TaskEnqueueResponse:
    task = poll_all_printers_task.delay(body.printer_type)
    worker_tasks_enqueued_total.labels(operation="poll_all_printers").inc()
    return TaskEnqueueResponse(task_id=task.id, state=task.state, operation="poll_all_printers")


@router.post("/poll-media-players", response_model=TaskEnqueueResponse)
def enqueue_poll_media_players(body: MediaPollTaskRequest, current_user: CurrentUser) -> TaskEnqueueResponse:
    task = poll_all_media_players_task.delay(body.device_type)
    worker_tasks_enqueued_total.labels(operation="poll_all_media_players").inc()
    return TaskEnqueueResponse(task_id=task.id, state=task.state, operation="poll_all_media_players")


@router.post("/poll-switch", response_model=TaskEnqueueResponse)
def enqueue_poll_switch(body: SwitchPollTaskRequest, current_user: CurrentUser) -> TaskEnqueueResponse:
    task = poll_switch_task.delay(body.switch_id)
    worker_tasks_enqueued_total.labels(operation="poll_switch").inc()
    return TaskEnqueueResponse(task_id=task.id, state=task.state, operation="poll_switch")


@router.post("/poll-switches", response_model=TaskEnqueueResponse)
def enqueue_poll_switches(current_user: CurrentUser) -> TaskEnqueueResponse:
    task = poll_all_switches_task.delay()
    worker_tasks_enqueued_total.labels(operation="poll_all_switches").inc()
    return TaskEnqueueResponse(task_id=task.id, state=task.state, operation="poll_all_switches")


@router.post("/ml-run-cycle", response_model=TaskEnqueueResponse, dependencies=[Depends(get_current_active_superuser)])
def enqueue_ml_run_cycle(body: MLCycleTaskRequest) -> TaskEnqueueResponse:
    del body
    task = ml_run_cycle_task.delay()
    worker_tasks_enqueued_total.labels(operation="ml_run_cycle").inc()
    return TaskEnqueueResponse(task_id=task.id, state=task.state, operation="ml_run_cycle")


@router.get("/{task_id}", response_model=TaskStatusResponse)
def get_task_status(task_id: str, current_user: CurrentUser) -> TaskStatusResponse:
    result = AsyncResult(task_id, app=celery_app)
    worker_task_status_checks_total.labels(state=result.state).inc()
    payload = TaskStatusResponse(
        task_id=task_id,
        state=result.state,
        ready=result.ready(),
        successful=result.successful() if result.ready() else None,
    )

    if result.failed():
        payload.error = str(result.result)
    elif result.successful() and isinstance(result.result, dict):
        payload.result = result.result
    elif result.successful() and result.result is not None:
        payload.result = {"value": str(result.result)}

    if result.state == "PENDING" and not result.result:
        return payload
    if result.state == "REVOKED":
        raise HTTPException(status_code=410, detail="Task has been revoked")
    return payload
