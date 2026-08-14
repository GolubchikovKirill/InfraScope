from __future__ import annotations

import asyncio
import re
import uuid
from contextlib import suppress
from dataclasses import dataclass
from time import monotonic

from fastapi import HTTPException
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.api.routes._service_errors import conflict, not_found
from app.core.config import settings
from app.core.redis import get_redis
from app.core.redis_lock import acquire_redis_lock, release_redis_lock, renew_redis_lock
from app.domains.inventory.models import NetworkSwitch
from app.services.cache import invalidate_entity_cache

CACHE_TTL = 30
_MIN_SWITCH_WRITE_LEASE_SECONDS = 300

_local_safety_mutex = asyncio.Lock()
_local_switch_cooldowns: dict[str, float] = {}
_SAFE_PORT_PATTERN = re.compile(
    r"^(?:"
    r"Gi|GigabitEthernet|"
    r"Fa|FastEthernet|"
    r"Te|TenGigabitEthernet|"
    r"Twe|TwentyFiveGigE|"
    r"Po|Port-channel"
    r")\d+(?:/\d+){0,3}$",
    re.IGNORECASE,
)


@dataclass
class _SwitchWriteLease:
    key: str
    owner: str
    ttl_seconds: int
    renewal_task: asyncio.Task[None] | None = None


async def _renew_switch_write_lease(lease: _SwitchWriteLease) -> None:
    """Keep a live hardware-operation lease alive until its request exits."""

    interval = max(1, min(30, lease.ttl_seconds // 3))
    while True:
        try:
            await asyncio.sleep(interval)
            redis = await asyncio.wait_for(get_redis(), timeout=0.2)
            renewed = await asyncio.wait_for(
                renew_redis_lock(redis, lease.key, lease.owner, ttl_seconds=lease.ttl_seconds),
                timeout=0.3,
            )
            if renewed is False:
                # Never delete a lease that another request has obtained.
                return
        except asyncio.CancelledError:
            raise
        except Exception:
            # New writes fail closed if Redis is unavailable. Keep retrying
            # while the current TTL protects this in-flight operation.
            continue


def _validate_switch_port(port: str) -> str:
    value = port.strip()
    if not value or len(value) > 64:
        raise HTTPException(status_code=422, detail="Invalid switch port identifier")
    if not _SAFE_PORT_PATTERN.match(value):
        raise HTTPException(status_code=422, detail="Unsafe or unsupported switch port format")
    return value


async def _acquire_switch_write_lock(switch_id: uuid.UUID) -> _SwitchWriteLease:
    lock_key = f"lock:switch-write:{switch_id}"
    try:
        r = await asyncio.wait_for(get_redis(), timeout=0.2)
        ttl_seconds = max(int(settings.SWITCH_WRITE_LOCK_SECONDS), _MIN_SWITCH_WRITE_LEASE_SECONDS)
        owner = await asyncio.wait_for(
            acquire_redis_lock(r, lock_key, ttl_seconds=ttl_seconds),
            timeout=0.3,
        )
        if owner is None:
            raise HTTPException(status_code=409, detail="Another switch write operation is already running")
        lease = _SwitchWriteLease(key=lock_key, owner=owner, ttl_seconds=ttl_seconds)
        lease.renewal_task = asyncio.create_task(_renew_switch_write_lease(lease))
        return lease
    except HTTPException:
        raise
    except Exception as exc:
        # A process-local fallback would let separate API workers power-cycle
        # the same switch concurrently. Hardware operations must fail closed.
        raise HTTPException(
            status_code=503,
            detail="Switch control is temporarily unavailable because its distributed safety lock cannot be acquired",
        ) from exc


async def _release_switch_write_lock(lease: _SwitchWriteLease | None) -> None:
    if lease is None:
        return
    if lease.renewal_task is not None:
        lease.renewal_task.cancel()
        with suppress(asyncio.CancelledError):
            await lease.renewal_task
    try:
        redis = await asyncio.wait_for(get_redis(), timeout=0.2)
        await asyncio.wait_for(release_redis_lock(redis, lease.key, lease.owner), timeout=0.3)
    except Exception:
        # The lease expires safely if Redis cannot be reached during cleanup.
        pass


async def _enforce_switch_cooldown(*, switch_id: uuid.UUID, port: str, operation: str) -> None:
    cooldown = max(int(settings.SWITCH_SAFETY_COOLDOWN_SECONDS), 0)
    if cooldown == 0:
        return
    cooldown_key = f"cooldown:switch-write:{switch_id}:{operation}:{port}"
    try:
        r = await asyncio.wait_for(get_redis(), timeout=0.2)
        ok = await asyncio.wait_for(r.set(cooldown_key, "1", ex=cooldown, nx=True), timeout=0.3)
        if not ok:
            raise HTTPException(
                status_code=429,
                detail=f"Operation throttled by safety cooldown ({cooldown}s). Try again later.",
            )
    except HTTPException:
        raise
    except Exception:
        now = monotonic()
        async with _local_safety_mutex:
            existing = _local_switch_cooldowns.get(cooldown_key)
            if existing and existing > now:
                raise HTTPException(
                    status_code=429,
                    detail=f"Operation throttled by safety cooldown ({cooldown}s). Try again later.",
                )
            _local_switch_cooldowns[cooldown_key] = now + cooldown


def _get_switch_or_404(session: SessionDep, switch_id: uuid.UUID) -> NetworkSwitch:
    switch = session.get(NetworkSwitch, switch_id)
    if not switch:
        raise not_found("Switch not found")
    return switch


def _ensure_unique_switch_ip(
    session: SessionDep,
    ip_address: str,
    *,
    excluded_switch_id: uuid.UUID | None = None,
    conflict_status_code: int = 409,
) -> None:
    filters = [NetworkSwitch.ip_address == ip_address]
    if excluded_switch_id is not None:
        filters.append(NetworkSwitch.id != excluded_switch_id)
    existing = session.exec(select(NetworkSwitch).where(*filters)).first()
    if existing:
        raise conflict("Switch with this IP already exists", status_code=conflict_status_code)


async def _invalidate_cache() -> None:
    await invalidate_entity_cache("switches")


async def _invalidate_ports_cache(switch_id: uuid.UUID) -> None:
    await invalidate_entity_cache(f"switch_ports:{switch_id}")


def _require_superuser(current_user: CurrentUser) -> None:
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Only superusers can perform write operations")
