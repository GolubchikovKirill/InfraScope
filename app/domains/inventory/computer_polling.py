from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlmodel import Session, select

from app.core.config import settings
from app.core.redis import get_redis
from app.domains.inventory.models import Computer
from app.domains.inventory.reachability import build_dns_search_suffixes, probe_host_ports
from app.domains.inventory.schemas import ComputersPublic
from app.services.cache import invalidate_entity_cache

logger = logging.getLogger(__name__)

_COMPUTER_PROBE_PORTS = (445, 3389, 135)


async def invalidate_computer_cache() -> None:
    await invalidate_entity_cache("computers")


def probe_computer(hostname: str) -> tuple[bool, str | None]:
    suffixes = build_dns_search_suffixes(settings.DNS_SEARCH_SUFFIXES, settings.DOMAIN)
    result = probe_host_ports(
        hostname,
        ports=_COMPUTER_PROBE_PORTS,
        timeout=1.2,
        probe_scope="computers",
        max_attempts=settings.NETWORK_PROBE_MAX_ATTEMPTS,
        retry_backoff_seconds=settings.NETWORK_PROBE_RETRY_BACKOFF_SECONDS,
        timeout_multiplier=settings.NETWORK_PROBE_TIMEOUT_MULTIPLIER,
        dns_search_suffixes=suffixes,
        dns_server=settings.DNS_SERVER,
    )
    return result.is_online, result.reason


async def probe_computers_bulk(rows: list[Computer]) -> dict:
    semaphore = asyncio.Semaphore(max(1, settings.COMPUTER_POLL_CONCURRENCY))

    async def _run(row: Computer) -> tuple:
        async with semaphore:
            return row.id, await asyncio.to_thread(probe_computer, row.hostname)

    pairs = await asyncio.gather(*[_run(row) for row in rows]) if rows else []
    return dict(pairs)


async def poll_all_computers_local(*, session: Session) -> ComputersPublic:
    lock_key = "lock:poll-all:computers"
    lock_acquired = True
    try:
        redis = await get_redis()
        lock_acquired = bool(await redis.set(lock_key, "1", ex=320, nx=True))
    except Exception:
        lock_acquired = True

    rows = session.exec(select(Computer)).all()
    if not lock_acquired:
        logger.info("Skipping duplicate poll-all request for computers: lock busy")
        return ComputersPublic(data=rows, count=len(rows))

    try:
        probe_results = await probe_computers_bulk(rows)
        now = datetime.now(UTC)
        for row in rows:
            is_online, reason = probe_results.get(row.id, (False, "probe_failed"))
            row.is_online = is_online
            row.reachability_reason = reason
            row.last_polled_at = now
            session.add(row)
        session.commit()
        await invalidate_computer_cache()
        return ComputersPublic(data=rows, count=len(rows))
    finally:
        if lock_acquired:
            try:
                redis = await get_redis()
                await redis.delete(lock_key)
            except Exception:
                pass
