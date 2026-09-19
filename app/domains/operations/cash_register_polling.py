from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from sqlmodel import Session, select

from app.core.config import settings
from app.core.redis import REDIS_ERRORS, get_redis
from app.domains.inventory.reachability import (
    REASON_PROBE_ERROR,
    ReachabilityResult,
    build_dns_search_suffixes,
    probe_host_ports,
)
from app.domains.operations.models import CashRegister
from app.domains.operations.schemas import CashRegistersPublic
from app.services.cache import invalidate_entity_cache
from app.services.event_log import write_event_log
from app.services.poll_resilience import apply_poll_outcome, is_circuit_open, poll_jitter_sync

logger = logging.getLogger(__name__)


class CashRegisterNotFoundError(LookupError):
    pass


async def invalidate_cash_register_cache() -> None:
    await invalidate_entity_cache("cash_registers")


def probe_cash_register(hostname: str) -> ReachabilityResult:
    suffixes = build_dns_search_suffixes(settings.DNS_SEARCH_SUFFIXES, settings.DOMAIN)
    poll_jitter_sync()
    return probe_host_ports(
        hostname,
        ports=(3389, 445),
        timeout=1.5,
        probe_scope="cash_registers",
        max_attempts=settings.NETWORK_PROBE_MAX_ATTEMPTS,
        retry_backoff_seconds=settings.NETWORK_PROBE_RETRY_BACKOFF_SECONDS,
        timeout_multiplier=settings.NETWORK_PROBE_TIMEOUT_MULTIPLIER,
        dns_search_suffixes=suffixes,
        dns_server=settings.DNS_SERVER,
    )


_OFFLINE_REASON_RU = {
    "dns_unresolved": "hostname не резолвится",
    "port_closed": "сетевые порты недоступны",
    "no_route": "нет маршрута до хоста",
    "no_response": "хост не отвечает",
    "probe_error": "сбой самой проверки",
}


def cash_register_offline_reason_ru(reason: str | None) -> str:
    return _OFFLINE_REASON_RU.get(reason or "", "хост недоступен")


def apply_cash_register_poll_result(cash: CashRegister, *, is_online: bool, reason: str | None) -> None:
    cash.is_online = is_online
    cash.reachability_reason = reason
    cash.last_polled_at = datetime.now(UTC)


async def _probe_cash_registers_bulk(rows: list[CashRegister]) -> dict[uuid.UUID, ReachabilityResult]:
    semaphore = asyncio.Semaphore(max(1, settings.CASH_REGISTER_POLL_CONCURRENCY))

    async def _run(row: CashRegister) -> tuple[uuid.UUID, ReachabilityResult]:
        async with semaphore:
            return row.id, await asyncio.to_thread(probe_cash_register, row.hostname)

    pairs = await asyncio.gather(*[_run(row) for row in rows]) if rows else []
    return dict(pairs)


def record_cash_register_status_change(
    session: Session,
    cash: CashRegister,
    previous_online: bool | None,
) -> None:
    if previous_online == cash.is_online:
        return
    if cash.is_online:
        write_event_log(
            session,
            event_type="cash_register_online",
            category="availability",
            severity="info",
            device_kind="cash_register",
            device_name=f"ККМ №{cash.kkm_number}",
            ip_address=cash.hostname,
            message=f"Касса ККМ №{cash.kkm_number} снова online ({cash.hostname})",
        )
        return

    reason = cash_register_offline_reason_ru(cash.reachability_reason)
    write_event_log(
        session,
        event_type="cash_register_offline",
        category="availability",
        severity="warning",
        device_kind="cash_register",
        device_name=f"ККМ №{cash.kkm_number}",
        ip_address=cash.hostname,
        message=f"Касса ККМ №{cash.kkm_number} offline ({reason})",
    )


async def poll_single_cash_register_local(*, session: Session, cash_id: uuid.UUID) -> CashRegister:
    cash = session.get(CashRegister, cash_id)
    if not cash:
        raise CashRegisterNotFoundError("Cash register not found")

    previous_online = cash.is_online
    # A manual poll is a person asking right now, so it bypasses the circuit
    # breaker on purpose - that is also how someone confirms a register is
    # back before the breaker's own window would have retried it.
    probe = await asyncio.to_thread(probe_cash_register, cash.hostname)
    apply_cash_register_poll_result(cash, is_online=probe.is_online, reason=probe.reason)
    record_cash_register_status_change(session, cash, previous_online)
    session.add(cash)
    session.commit()
    session.refresh(cash)
    await invalidate_cash_register_cache()
    return cash


async def poll_all_cash_registers_local(*, session: Session) -> CashRegistersPublic:
    lock_key = "lock:poll-all:cash-registers"
    lock_acquired = True
    try:
        redis = await get_redis()
        lock_acquired = bool(await redis.set(lock_key, "1", ex=320, nx=True))
    except REDIS_ERRORS as exc:
        # Fail open: a Redis outage must not stop polling; the worst case is a duplicate poll.
        logger.warning("Poll lock %s unavailable, polling without it: %s", lock_key, exc)
        lock_acquired = True

    rows = session.exec(select(CashRegister)).all()
    if not lock_acquired:
        return CashRegistersPublic(data=rows, count=len(rows))

    try:
        poll_targets = [row for row in rows if not await is_circuit_open("cash_register", str(row.id))]
        probe_results = await _probe_cash_registers_bulk(poll_targets)
        now = datetime.now(UTC)
        for row in rows:
            probe = probe_results.get(row.id)
            if probe is None:
                # Circuit open: leave the row exactly as it was, including
                # last_polled_at, so the UI shows the age of the real answer
                # rather than the age of a poll that never happened.
                continue
            previous_online = row.is_online
            row.is_online = await apply_poll_outcome(
                kind="cash_register",
                entity_id=str(row.id),
                previous_effective_online=bool(row.is_online),
                probed_online=probe.is_online,
                probed_error=probe.is_path_failure,
            )
            row.reachability_reason = None if row.is_online else (probe.reason or REASON_PROBE_ERROR)
            row.last_polled_at = now
            record_cash_register_status_change(session, row, previous_online)
            session.add(row)

        session.commit()
        result = session.exec(select(CashRegister).order_by(CashRegister.kkm_number)).all()
        await invalidate_cash_register_cache()
        return CashRegistersPublic(data=result, count=len(result))
    finally:
        if lock_acquired:
            try:
                redis = await get_redis()
                await redis.delete(lock_key)
            except REDIS_ERRORS as exc:
                # The lock expires on its own (ex=320); nothing else to do.
                logger.debug("Could not release poll lock %s: %s", lock_key, exc)
