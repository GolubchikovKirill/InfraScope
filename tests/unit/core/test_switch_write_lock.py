from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, *, ex: int, nx: bool) -> bool:
        del ex
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, script: str, _keys: int, key: str, owner: str, *args) -> int:
        if self.values.get(key) != owner:
            return 0
        if "del" in script:
            del self.values[key]
            return 1
        del args
        return 1


@pytest.mark.asyncio
async def test_switch_write_lock_never_releases_a_new_owner(monkeypatch) -> None:
    from app.api.routes.switches import _shared

    redis = _FakeRedis()

    async def _get_redis():
        return redis

    monkeypatch.setattr(_shared, "get_redis", _get_redis)

    lease = await _shared._acquire_switch_write_lock(uuid.uuid4())
    redis.values[lease.key] = "new-operation-owner"
    await _shared._release_switch_write_lock(lease)

    assert redis.values[lease.key] == "new-operation-owner"


@pytest.mark.asyncio
async def test_switch_write_is_rejected_when_distributed_lock_is_unavailable(monkeypatch) -> None:
    from app.api.routes.switches import _shared

    async def _unavailable():
        raise OSError("Redis unavailable")

    monkeypatch.setattr(_shared, "get_redis", _unavailable)

    with pytest.raises(HTTPException) as exc:
        await _shared._acquire_switch_write_lock(uuid.uuid4())

    assert exc.value.status_code == 503
