from __future__ import annotations

import asyncio
import functools
import secrets
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter

import redis
from celery import shared_task
from redis.exceptions import RedisError
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.core.redis import close_redis
from app.domains.inventory.ap_auto_reboot import (
    get_eligible_switches_for_auto_reboot,
    parse_allowed_stores,
    run_ap_reboot_for_switch,
    switch_eligible_for_auto_reboot,
)
from app.domains.inventory.models import Computer, MediaPlayer, NetworkSwitch, Printer
from app.domains.inventory.port_snapshot import capture_switch_port_snapshot, get_switches_for_snapshot
from app.domains.operations.models import CashRegister
from app.domains.remote_access import rustdesk_client as _rustdesk_client
from app.domains.remote_access import service as _remote_access_service
from app.ml.pipeline import run_scoring_cycle, run_training_cycle
from app.ml.retention import run_retention_cycle
from app.observability.metrics import (
    ml_train_runs_total,
    worker_task_duration_seconds,
    worker_task_executions_total,
    worker_tasks_enqueued_total,
    worker_tasks_in_progress,
)
from app.services.discovery import run_discovery_scan
from app.services.polling_orchestrator import (
    poll_all_cash_registers_local,
    poll_all_computers_local,
    poll_all_media_players_local,
    poll_all_printers_local,
    poll_all_switches_local,
    poll_switch_local,
)
from app.services.scanner import scan_subnet


@dataclass
class _AutoRebootLease:
    """Redis-backed lease for a live AP reboot task.

    The broker can redeliver an ETA task before the original worker has
    acknowledged it.  A per-switch lease prevents the duplicate from touching
    hardware, while the completed marker makes late redelivery idempotent.
    """

    client: redis.Redis
    lock_key: str
    done_key: str
    token: str

    def mark_attempted(self) -> None:
        # Compare-and-delete prevents one expired/replaced lease holder from
        # clearing a newer task's lock.  Persisting the marker before release
        # makes every outcome (including a partial hardware failure) safe from
        # automatic repetition; a human can start a new manual cycle instead.
        self.client.eval(
            """
            if redis.call('GET', KEYS[1]) == ARGV[1] then
                redis.call('SET', KEYS[2], '1', 'EX', ARGV[2])
                redis.call('DEL', KEYS[1])
                return 1
            end
            return 0
            """,
            2,
            self.lock_key,
            self.done_key,
            self.token,
            settings.AUTO_REBOOT_AP_CYCLE_DEDUP_SECONDS,
        )

    def close(self) -> None:
        try:
            self.client.close()
        except RedisError:
            pass


def _acquire_auto_reboot_lease(*, switch_id: str, cycle_id: str) -> tuple[_AutoRebootLease | None, str | None]:
    """Acquire a fail-closed distributed lease for live switch operations."""
    lock_key = f"lock:ap-auto-reboot:switch:{switch_id}"
    done_key = f"done:ap-auto-reboot:{switch_id}:{cycle_id}"
    token = secrets.token_urlsafe(24)
    client = redis.Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    try:
        # This check-and-lock needs to be one Redis operation.  Reading the
        # done key and then SET NX separately leaves a race after a first task
        # releases its lease.
        claimed = client.eval(
            """
            if redis.call('EXISTS', KEYS[2]) == 1 then
                return 0
            end
            if redis.call('SET', KEYS[1], ARGV[1], 'NX', 'EX', ARGV[2]) then
                return 1
            end
            return -1
            """,
            2,
            lock_key,
            done_key,
            token,
            settings.AUTO_REBOOT_AP_TASK_LOCK_SECONDS,
        )
    except RedisError:
        client.close()
        # Hardware writes must not proceed when the only duplicate-action
        # guard is unavailable.
        return None, "lock_unavailable"

    if claimed == 1:
        return _AutoRebootLease(client=client, lock_key=lock_key, done_key=done_key, token=token), None

    client.close()
    return None, "already_attempted" if claimed == 0 else "already_running"


def _run_async(coro):
    """asyncio.run() for Celery tasks that also closes this loop's Redis pool.

    Each task gets its own event loop, and an asyncio Redis pool is bound to
    the loop that created it (see app.core.redis). Closing it here, before the
    loop is torn down, keeps connections from outliving their loop.
    """

    async def _runner():
        try:
            return await coro
        finally:
            await close_redis()

    return asyncio.run(_runner())


def _task_started(operation: str) -> float:
    worker_tasks_in_progress.labels(operation=operation).inc()
    return perf_counter()


def _task_finished(operation: str, started_at: float, result: str) -> None:
    worker_tasks_in_progress.labels(operation=operation).dec()
    worker_task_executions_total.labels(operation=operation, result=result).inc()
    worker_task_duration_seconds.labels(operation=operation).observe(max(perf_counter() - started_at, 0))


class _Skipped(dict):
    """Returned by a task body that deliberately did nothing (recorded as
    result="skipped" in the task metrics instead of "success")."""


class _Failed(dict):
    """Returned by a task body that ended without raising but did not succeed
    (recorded as result="error", and not retried)."""


def _task(name: str, *, retries: int | None = None, **celery_options):
    """Declare a Celery task with its metrics and result envelope.

    The decorated function is the task body only: it returns the task-specific
    fields (or `_Skipped(...)` / `_Failed(...)`). This wrapper owns what every
    task used to repeat by hand:

    * the in-progress gauge, execution counter and duration histogram, labelled
      with `name` as the operation (an exception counts as "error", then
      propagates so Celery's retry/failure handling still sees it);
    * the `task_id` / `operation` / `finished_at` envelope of the result;
    * `autoretry_for` with exponential backoff when `retries` is given. Tasks
      that touch hardware or are started by a person pass no `retries`.
    """
    retry = (
        {"autoretry_for": (Exception,), "retry_backoff": True, "retry_kwargs": {"max_retries": retries}}
        if retries
        else {}
    )

    def decorate(body):
        @functools.wraps(body)
        def run(self, *args, **kwargs) -> dict:
            started_at = _task_started(name)
            try:
                outcome = body(self, *args, **kwargs)
            except Exception:
                _task_finished(name, started_at, "error")
                raise
            label = "skipped" if isinstance(outcome, _Skipped) else "error" if isinstance(outcome, _Failed) else "success"
            _task_finished(name, started_at, label)
            payload = dict(outcome)
            payload.setdefault("task_id", self.request.id)
            payload.setdefault("operation", name)
            payload.setdefault("finished_at", datetime.now(UTC).isoformat())
            return payload

        return shared_task(bind=True, name=f"tasks.{name}", **retry, **celery_options)(run)

    return decorate


def _known_printers() -> list[dict]:
    with Session(engine) as session:
        return [
            {"id": str(p.id), "ip_address": p.ip_address, "mac_address": p.mac_address, "store_name": p.store_name}
            for p in session.exec(select(Printer)).all()
        ]


@_task("scan_network", retries=3)
def scan_network_task(self, subnet: str, ports: str) -> dict:
    devices = _run_async(scan_subnet(subnet, ports, _known_printers()))
    return {"subnet": subnet, "ports": ports, "found_devices": len(devices)}


# No retries: a scan is started by a person, and a failed one already reports
# its error through the progress key the UI polls.
@_task("discovery_scan", soft_time_limit=1500, time_limit=1800)
def discovery_scan_task(self, kind: str, subnet: str, ports: str, known: list[dict]) -> dict:
    """Network discovery scan ("printers", "iconbit" or "switch").

    Progress and results live in Redis (see app.services.scanner/discovery),
    which is what the status/results endpoints read.
    """
    if kind == "printers":
        devices = _run_async(scan_subnet(subnet, ports, known))
    else:
        devices = _run_async(run_discovery_scan(kind, subnet, ports, known))
    return {"kind": kind, "found_devices": len(devices)}


@_task("poll_all_printers", retries=2)
def poll_all_printers_task(self, printer_type: str = "laser") -> dict:
    with Session(engine) as session:
        _run_async(poll_all_printers_local(session=session, printer_type=printer_type))
        printers = session.exec(select(Printer).where(Printer.printer_type == printer_type)).all()
    return {"printer_type": printer_type, "total": len(printers), "online": sum(1 for p in printers if p.is_online)}


@_task("poll_all_media_players", retries=2)
def poll_all_media_players_task(self, device_type: str | None = None) -> dict:
    with Session(engine) as session:
        _run_async(poll_all_media_players_local(session=session, device_type=device_type))
        statement = select(MediaPlayer)
        if device_type:
            statement = statement.where(MediaPlayer.device_type == device_type)
        players = session.exec(statement).all()
    return {"device_type": device_type, "total": len(players), "online": sum(1 for p in players if p.is_online)}


@_task("poll_switch", retries=2)
def poll_switch_task(self, switch_id: str) -> dict:
    with Session(engine) as session:
        sw = _run_async(poll_switch_local(switch_id=uuid.UUID(switch_id), session=session))
    return {"switch_id": switch_id, "is_online": bool(sw.is_online), "hostname": sw.hostname}


@_task("poll_all_switches", retries=2)
def poll_all_switches_task(self) -> dict:
    # The bulk poll, not a per-switch loop: it is what the polling service ran
    # (concurrent, bounded by SWITCH_POLL_MAX_CONCURRENCY, and it detects "the
    # whole subnet went dark" as a path failure instead of recording N false
    # outages). The worker's own fallback used to poll one switch at a time and
    # skipped both.
    with Session(engine) as session:
        _run_async(poll_all_switches_local(session=session))
        switches = session.exec(select(NetworkSwitch)).all()
        results = [{"switch_id": str(sw.id), "name": sw.name, "is_online": bool(sw.is_online)} for sw in switches]
    return {"total": len(results), "online": sum(1 for r in results if r["is_online"]), "switches": results}


@_task("poll_all_computers", retries=2)
def poll_all_computers_task(self) -> dict:
    with Session(engine) as session:
        _run_async(poll_all_computers_local(session=session))
        computers = session.exec(select(Computer)).all()
    return {"total": len(computers), "online": sum(1 for c in computers if c.is_online)}


@_task("poll_all_cash_registers", retries=2)
def poll_all_cash_registers_task(self) -> dict:
    with Session(engine) as session:
        _run_async(poll_all_cash_registers_local(session=session))
        registers = session.exec(select(CashRegister)).all()
    return {"total": len(registers), "online": sum(1 for r in registers if r.is_online)}


@_task("ap_auto_reboot_cycle", soft_time_limit=300, time_limit=600)
def ap_auto_reboot_cycle_task(self) -> dict:
    """Dispatcher: fans out one independent task per eligible switch instead
    of rebooting all of them inline. With many switches allowed at once this
    avoids two problems a single big loop would have - every switch's PoE
    cycle landing on the network in the same few seconds, and the whole
    cycle blowing through one task's time limit partway through a large
    fleet (leaving the rest of that day's switches unprocessed with no
    record of why). Each switch's own reboot keeps its own no-autoretry
    time-limited task, unaffected by any other switch's outcome.
    """
    with Session(engine) as session:
        switches = get_eligible_switches_for_auto_reboot(session)
        stagger = max(settings.AUTO_REBOOT_AP_STAGGER_SECONDS, 0)
        cycle_id = self.request.id or str(uuid.uuid4())
        for index, switch in enumerate(switches):
            ap_auto_reboot_switch_task.apply_async(args=[str(switch.id), cycle_id], countdown=index * stagger)
            worker_tasks_enqueued_total.labels(operation="ap_auto_reboot_switch").inc()
    return {
        "status": "dispatched",
        "switches_scheduled": len(switches),
        "stagger_seconds": stagger,
        "cycle_id": cycle_id,
    }


# No retries: this reboots live hardware. If a cycle errors partway through,
# retrying could double-reboot an AP that already came back up. A failure is
# logged (event_log + task result) for manual follow-up instead of retried
# automatically.
@_task("ap_auto_reboot_switch", soft_time_limit=1700, time_limit=1800)
def ap_auto_reboot_switch_task(self, switch_id: str, cycle_id: str | None = None) -> dict:
    cycle_id = cycle_id or self.request.id or f"manual:{uuid.uuid4()}"
    lease, skipped_reason = _acquire_auto_reboot_lease(switch_id=switch_id, cycle_id=cycle_id)
    if lease is None:
        return _Skipped({"switch_id": switch_id, "cycle_id": cycle_id, "status": skipped_reason})
    try:
        with Session(engine) as session:
            switch = session.get(NetworkSwitch, uuid.UUID(switch_id))
            if switch is None:
                return _Failed({"status": "switch_not_found", "switch_id": switch_id})

            # Re-check eligibility at execution time, not just at dispatch:
            # a staggered fleet can span the better part of an hour, long
            # enough for someone to flip the toggle or the allowlist off
            # in between.
            if not switch.auto_reboot_aps_enabled:
                return _Skipped({"status": "disabled_since_dispatch", "switch": switch.name})

            allowed_stores = parse_allowed_stores(settings.AUTO_REBOOT_AP_ALLOWED_STORES)
            eligible, reason = switch_eligible_for_auto_reboot(switch, allowed_stores)
            if not eligible:
                return _Skipped({"status": "no_longer_eligible", "switch": switch.name, "reason": reason})

            result = _run_async(run_ap_reboot_for_switch(session, switch))
        return {"cycle_id": cycle_id, **result}
    finally:
        # Mark even an exception as attempted.  A task can fail after a PoE
        # command has already reached the switch, so automatic redelivery is
        # less safe than requiring an explicit operator decision.
        try:
            lease.mark_attempted()
        except RedisError:
            pass
        finally:
            lease.close()


@_task("switch_port_snapshot_cycle", soft_time_limit=120, time_limit=300)
def switch_port_snapshot_cycle_task(self) -> dict:
    """Dispatcher: one independent, staggered task per switch, same reasoning
    as the AP-reboot dispatcher - avoid a simultaneous SSH/SNMP burst across
    the whole fleet and keep one switch's failure from blocking the rest.
    Purely read-only (see app.domains.inventory.port_snapshot), so unlike the
    AP reboot dispatcher there's no eligibility/allowlist gating here.
    """
    with Session(engine) as session:
        switches = get_switches_for_snapshot(session)
        stagger = max(settings.SWITCH_PORT_SNAPSHOT_STAGGER_SECONDS, 0)
        for index, switch in enumerate(switches):
            switch_port_snapshot_task.apply_async(args=[str(switch.id)], countdown=index * stagger)
            worker_tasks_enqueued_total.labels(operation="switch_port_snapshot").inc()
    return {"status": "dispatched", "switches_scheduled": len(switches), "stagger_seconds": stagger}


@_task("switch_port_snapshot", retries=2, soft_time_limit=120, time_limit=180)
def switch_port_snapshot_task(self, switch_id: str) -> dict:
    with Session(engine) as session:
        switch = session.get(NetworkSwitch, uuid.UUID(switch_id))
        if switch is None:
            return _Failed({"status": "switch_not_found", "switch_id": switch_id})
        snapshot = capture_switch_port_snapshot(session, switch)
        name = switch.name
    return {"switch": name, "status": "changed" if snapshot else "unchanged_or_unreachable"}


_ML_LOCK_KEY = "lock:ml-cycle"
# Longer than the task time limit below, so a killed task cannot leave the
# lock held past the point where the next scheduled run would want it.
_ML_LOCK_SECONDS = 1900


@contextmanager
def _ml_cycle_lock() -> Iterator[bool]:
    """One ML cycle at a time (daily train, 30-min score, manual run).

    Scoring deletes and rewrites the whole prediction tables, training rewrites
    the model registry; two of them interleaving would leave half-replaced
    predictions. Fails *open* when Redis is unreachable, unlike the AP-reboot
    lease: ML touches no hardware, so the worst outcome of a duplicate run is
    a wasted cycle, and a Redis blip must not stop forecasting.
    """
    token = secrets.token_urlsafe(16)
    client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=1, socket_timeout=1)
    acquired = False
    try:
        try:
            acquired = bool(client.set(_ML_LOCK_KEY, token, nx=True, ex=_ML_LOCK_SECONDS))
        except RedisError:
            acquired = True
            token = ""
        yield acquired
    finally:
        if acquired and token:
            with suppress(RedisError):
                if client.get(_ML_LOCK_KEY) == token:
                    client.delete(_ML_LOCK_KEY)
        with suppress(RedisError):
            client.close()


def _run_ml_cycle(*, train: bool, prune: bool) -> dict:
    """Shared body of the three ML tasks.

    This used to be the prediction-service container: it ran its own asyncio
    scheduler loop and the worker/API called it over HTTP. Now beat schedules
    these tasks (see celery_app.py) and they run in-process here, against the
    same database, with the same metrics.
    """
    if not settings.ML_ENABLED:
        return _Skipped({"status": "skipped", "reason": "ml_disabled"})
    with _ml_cycle_lock() as acquired:
        if not acquired:
            return _Skipped({"status": "skipped", "reason": "another_ml_cycle_running"})
        result: dict = {}
        with Session(engine) as session:
            if train:
                try:
                    result["train"] = run_training_cycle(session, min_train_rows=settings.ML_MIN_TRAIN_ROWS)
                except Exception:
                    ml_train_runs_total.labels(model_family="toner_forecast", result="error").inc()
                    ml_train_runs_total.labels(model_family="offline_risk", result="error").inc()
                    raise
            result["score"] = run_scoring_cycle(session)
        if prune:
            # After training+scoring have read the full retained window
            # (see app/ml/retention.py).
            with Session(engine) as session:
                result["retention"] = run_retention_cycle(
                    session,
                    snapshot_retention_days=settings.ML_FEATURE_SNAPSHOT_RETENTION_DAYS,
                    model_registry_keep_per_family=settings.ML_MODEL_REGISTRY_KEEP_PER_FAMILY,
                    batch_size=settings.ML_RETENTION_BATCH_SIZE,
                )
    return {"result": result}


@_task("ml_run_cycle", retries=1, soft_time_limit=1500, time_limit=1800)
def ml_run_cycle_task(self) -> dict:
    """Manual train + score (POST /ml/run-cycle, POST /tasks/ml-run-cycle)."""
    return _run_ml_cycle(train=True, prune=False)


@_task("ml_daily_cycle", retries=1, soft_time_limit=1500, time_limit=1800)
def ml_daily_cycle_task(self) -> dict:
    """Scheduled once a day at ML_RETRAIN_HOUR_UTC: train, score, then prune."""
    return _run_ml_cycle(train=True, prune=True)


@_task("ml_score_cycle", soft_time_limit=300, time_limit=600)
def ml_score_cycle_task(self) -> dict:
    """Scheduled every ML_SCORE_INTERVAL_MINUTES: refresh predictions only."""
    return _run_ml_cycle(train=False, prune=False)


@_task("remote_access_sync", retries=2)
def remote_access_sync_task(self) -> dict:
    """Mirror inventory into RemoteAccessDevice rows + fold in live RustDesk-console status."""
    if not settings.REMOTE_ACCESS_ENABLED:
        return _Skipped({"status": "skipped"})
    with Session(engine) as session:
        seeded = _remote_access_service.seed_from_inventory(session)
        # a dead console token must not sink the whole sync (inventory + host
        # status still work); the page's "console down" banner surfaces it
        peers_seen = 0
        accounts_seen = 0
        book_pushed = 0
        console_error = None
        if _rustdesk_client.enabled():
            try:
                peers_seen = _run_async(_remote_access_service.sync_from_console(session)).get("peers_seen", 0)
                accounts_seen = _run_async(_remote_access_service.sync_accounts(session)).get("accounts_seen", 0)
                # only rows the console is missing or whose password went stale
                book_pushed = _run_async(_remote_access_service.sync_stale_address_book(session)).get("pushed", 0)
            except Exception as exc:  # noqa: BLE001
                console_error = str(exc)
        statuses = _remote_access_service.refresh_status_from_inventory(session)
    return {
        "seeded": seeded,
        "peers_seen": peers_seen,
        "accounts_seen": accounts_seen,
        "address_book_pushed": book_pushed,
        "statuses_from_polling": statuses,
        "console_error": console_error,
    }
