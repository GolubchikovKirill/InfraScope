from __future__ import annotations

import asyncio
import re
import uuid
from time import monotonic

from fastapi import HTTPException
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.api.routes._service_errors import conflict, not_found
from app.core.config import settings
from app.core.redis import get_redis
from app.domains.inventory.models import NetworkSwitch
from app.services.cache import invalidate_entity_cache

CACHE_TTL = 30

_local_safety_mutex = asyncio.Lock()
_local_switch_write_locks: dict[str, float] = {}
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


def _validate_switch_port(port: str) -> str:
    value = port.strip()
    if not value or len(value) > 64:
        raise HTTPException(status_code=422, detail="Invalid switch port identifier")
    if not _SAFE_PORT_PATTERN.match(value):
        raise HTTPException(status_code=422, detail="Unsafe or unsupported switch port format")
    return value


async def _acquire_switch_write_lock(switch_id: uuid.UUID) -> str | None:
    lock_key = f"lock:switch-write:{switch_id}"
    try:
        r = await asyncio.wait_for(get_redis(), timeout=0.2)
        locked = await asyncio.wait_for(
            r.set(lock_key, "1", ex=settings.SWITCH_WRITE_LOCK_SECONDS, nx=True),
            timeout=0.3,
        )
        if not locked:
            raise HTTPException(status_code=409, detail="Another switch write operation is already running")
        return lock_key
    except HTTPException:
        raise
    except Exception:
        expires_at = monotonic() + max(int(settings.SWITCH_WRITE_LOCK_SECONDS), 1)
        async with _local_safety_mutex:
            existing = _local_switch_write_locks.get(lock_key)
            if existing and existing > monotonic():
                raise HTTPException(status_code=409, detail="Another switch write operation is already running")
            _local_switch_write_locks[lock_key] = expires_at
        return f"local:{lock_key}"


async def _release_switch_write_lock(lock_key: str | None) -> None:
    if not lock_key:
        return
    if lock_key.startswith("local:"):
        raw_key = lock_key.removeprefix("local:")
        async with _local_safety_mutex:
            _local_switch_write_locks.pop(raw_key, None)
        return
    try:
        r = await asyncio.wait_for(get_redis(), timeout=0.2)
        await asyncio.wait_for(r.delete(lock_key), timeout=0.3)
    except Exception:
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
