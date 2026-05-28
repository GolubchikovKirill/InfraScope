from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from time import perf_counter

from sqlmodel import Session, select

from app.core.config import settings
from app.core.redis import get_redis
from app.domains.inventory.models import NetworkSwitch
from app.domains.shared.schemas import Message
from app.observability.metrics import (
    network_bulk_operation_duration_seconds,
    network_bulk_processed_total,
    set_device_counts,
    switch_ops_total,
)
from app.services.event_log import write_event_log
from app.services.ml_snapshots import write_switch_snapshot
from app.services.poll_resilience import apply_poll_outcome, is_circuit_open, poll_jitter_async
from app.services.switches import resolve_switch_provider
from app.services.switches.base import SwitchPollInfo

logger = logging.getLogger(__name__)

class SwitchNotFoundError(LookupError):
    pass


def record_switch_status_change(session: Session, switch: NetworkSwitch, was_online: bool | None) -> None:
    if was_online is None or was_online == switch.is_online:
        return
    write_event_log(
        session,
        category="device",
        event_type="device_online" if switch.is_online else "device_offline",
        severity="info" if switch.is_online else "warning",
        device_kind="switch",
        device_name=switch.name,
        ip_address=switch.ip_address,
        message=f"Network device '{switch.name}' is now {'online' if switch.is_online else 'offline'}",
    )


def apply_switch_poll_info(
    switch: NetworkSwitch,
    info: SwitchPollInfo,
    *,
    effective_online: bool | None = None,
) -> None:
    switch.is_online = info.is_online if effective_online is None else effective_online
    switch.hostname = info.hostname or switch.hostname
    switch.model_info = info.model_info or switch.model_info
    switch.ios_version = info.ios_version or switch.ios_version
    switch.uptime = info.uptime or switch.uptime
    switch.last_polled_at = datetime.now(UTC)


async def poll_one_switch(switch: NetworkSwitch) -> tuple[NetworkSwitch, SwitchPollInfo | None, Exception | None]:
    try:
        await poll_jitter_async()
        provider = resolve_switch_provider(switch)
        info = await asyncio.to_thread(provider.poll_switch, switch)
        return switch, info, None
    except Exception as exc:
        return switch, None, exc


async def poll_single_switch_local(*, session: Session, switch_id: uuid.UUID) -> NetworkSwitch:
    switch = session.get(NetworkSwitch, switch_id)
    if not switch:
        raise SwitchNotFoundError("Switch not found")

    was_online = switch.is_online
    provider = resolve_switch_provider(switch)
    info = await asyncio.to_thread(provider.poll_switch, switch)
    apply_switch_poll_info(switch, info)
    switch_ops_total.labels(operation="poll", result="online" if info.is_online else "offline").inc()
    record_switch_status_change(session, switch, was_online)
    write_switch_snapshot(session, switch, source="single_poll")
    session.add(switch)
    session.commit()
    session.refresh(switch)
    return switch


async def poll_all_switches_local(*, session: Session) -> Message:
    started = perf_counter()
    lock_key = "lock:poll-all:switches"
    lock_acquired = True
    try:
        redis = await get_redis()
        lock_acquired = bool(await redis.set(lock_key, "1", ex=45, nx=True))
    except Exception:
        lock_acquired = True

    switches = session.exec(select(NetworkSwitch)).all()
    set_device_counts(
        kind="switch",
        total=len(switches),
        online=sum(1 for switch in switches if switch.is_online),
    )
    if not lock_acquired:
        logger.info("Skipping duplicate poll-all request for switches: lock busy")
        return Message(message="Switch poll already in progress")

    try:
        poll_targets: list[NetworkSwitch] = []
        for switch in switches:
            if await is_circuit_open("switch", str(switch.id)):
                switch_ops_total.labels(operation="poll_all", result="skipped").inc()
                continue
            poll_targets.append(switch)

        semaphore = asyncio.Semaphore(max(1, settings.SWITCH_POLL_MAX_CONCURRENCY))

        async def _limited_poll(switch: NetworkSwitch) -> tuple[NetworkSwitch, SwitchPollInfo | None, Exception | None]:
            async with semaphore:
                return await poll_one_switch(switch)

        results = await asyncio.gather(*[_limited_poll(switch) for switch in poll_targets]) if poll_targets else []
        error_count = 0

        for switch, info, exc in results:
            try:
                was_online = switch.is_online
                if exc:
                    raise exc
                if info is None:
                    raise RuntimeError("poll returned no data")

                effective_online = await apply_poll_outcome(
                    kind="switch",
                    entity_id=str(switch.id),
                    previous_effective_online=bool(switch.is_online),
                    probed_online=bool(info.is_online),
                    probed_error=False,
                )
                apply_switch_poll_info(switch, info, effective_online=effective_online)
                record_switch_status_change(session, switch, was_online)
                switch_ops_total.labels(operation="poll_all", result="online" if effective_online else "offline").inc()
                write_switch_snapshot(session, switch, source="bulk_poll")
                session.add(switch)
            except Exception as exc:
                logger.warning("Bulk switch poll failed for %s (%s): %s", switch.name, switch.ip_address, exc)
                write_event_log(
                    session,
                    category="system",
                    event_type="critical_poll_error",
                    severity="critical",
                    device_kind="switch",
                    device_name=switch.name,
                    ip_address=switch.ip_address,
                    message=f"Critical switch poll error for '{switch.name}': {exc}",
                )
                switch.is_online = await apply_poll_outcome(
                    kind="switch",
                    entity_id=str(switch.id),
                    previous_effective_online=bool(switch.is_online),
                    probed_online=False,
                    probed_error=True,
                )
                switch.last_polled_at = datetime.now(UTC)
                write_switch_snapshot(session, switch, source="bulk_poll_error")
                session.add(switch)
                switch_ops_total.labels(operation="poll_all", result="error").inc()
                error_count += 1

        session.commit()
        success_count = max(len(switches) - error_count, 0)
        network_bulk_processed_total.labels(operation="switch_poll_all", result="success").inc(success_count)
        if error_count:
            network_bulk_processed_total.labels(operation="switch_poll_all", result="error").inc(error_count)
        network_bulk_operation_duration_seconds.labels(operation="switch_poll_all").observe(
            max(perf_counter() - started, 0)
        )
        return Message(message="Switches polled")
    finally:
        if lock_acquired:
            try:
                redis = await get_redis()
                await redis.delete(lock_key)
            except Exception:
                pass
