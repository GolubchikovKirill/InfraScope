from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from sqlmodel import Session, select

from app.core.config import settings
from app.core.redis import get_redis
from app.domains.inventory.reachability import probe_host_ports
from app.domains.operations.models import CashRegister
from app.domains.operations.schemas import CashRegistersPublic
from app.services.cache import invalidate_entity_cache
from app.services.event_log import write_event_log


class CashRegisterNotFoundError(LookupError):
    pass


async def invalidate_cash_register_cache() -> None:
    await invalidate_entity_cache("cash_registers")


def probe_cash_register(hostname: str) -> tuple[bool, str | None]:
    result = probe_host_ports(
        hostname,
        ports=(3389, 445),
        timeout=1.5,
        dns_search_suffixes=settings.DNS_SEARCH_SUFFIXES,
        dns_server=settings.DNS_SERVER,
    )
    return result.is_online, result.reason


def cash_register_offline_reason_ru(reason: str | None) -> str:
    if reason == "dns_unresolved":
        return "hostname не резолвится"
    if reason == "port_closed":
        return "сетевые порты недоступны"
    return "хост недоступен"


def apply_cash_register_poll_result(cash: CashRegister, *, is_online: bool, reason: str | None) -> None:
    cash.is_online = is_online
    cash.reachability_reason = reason
    cash.last_polled_at = datetime.now(UTC)


async def _probe_cash_registers_bulk(rows: list[CashRegister]) -> dict[uuid.UUID, tuple[bool, str | None]]:
    semaphore = asyncio.Semaphore(max(1, settings.CASH_REGISTER_POLL_CONCURRENCY))

    async def _run(row: CashRegister) -> tuple[uuid.UUID, tuple[bool, str | None]]:
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
    is_online, reason = await asyncio.to_thread(probe_cash_register, cash.hostname)
    apply_cash_register_poll_result(cash, is_online=is_online, reason=reason)
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
        lock_acquired = bool(await redis.set(lock_key, "1", ex=45, nx=True))
    except Exception:
        lock_acquired = True

    rows = session.exec(select(CashRegister)).all()
    if not lock_acquired:
        return CashRegistersPublic(data=rows, count=len(rows))

    try:
        probe_results = await _probe_cash_registers_bulk(rows)
        now = datetime.now(UTC)
        for row in rows:
            previous_online = row.is_online
            is_online, reason = probe_results.get(row.id, (False, "probe_failed"))
            row.is_online = is_online
            row.reachability_reason = reason
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
            except Exception:
                pass
