from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.api.websockets import _authenticate_ws_token
from app.core.security import create_access_token, create_refresh_token
from app.domains.identity.models import User


class _FakeSession:
    def __init__(self, by_id=None) -> None:
        self._by_id = by_id or {}

    def get(self, _model, obj_id):
        return self._by_id.get(obj_id)

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        return None


def _user(*, active: bool = True) -> User:
    return User(email="ap-test@example.com", hashed_password="x", is_active=active)


@pytest.fixture(autouse=True)
def _not_blacklisted(monkeypatch):
    """is_token_blacklisted hits Redis; default it to reachable-and-clean so
    tests unrelated to blacklisting don't need Redis running. The one test
    that cares about blacklisting overrides this itself."""

    async def _fake(_jti: str) -> bool:
        return False

    monkeypatch.setattr("app.api.websockets.is_token_blacklisted", _fake)


@pytest.mark.asyncio
async def test_rejects_missing_token() -> None:
    assert await _authenticate_ws_token(None) is None


@pytest.mark.asyncio
async def test_rejects_garbage_token() -> None:
    assert await _authenticate_ws_token("not-a-real-jwt") is None


@pytest.mark.asyncio
async def test_rejects_refresh_token(monkeypatch) -> None:
    user = _user()
    monkeypatch.setattr("app.api.websockets.Session", lambda _engine: _FakeSession(by_id={user.id: user}))
    token = create_refresh_token(str(user.id))

    assert await _authenticate_ws_token(token) is None


@pytest.mark.asyncio
async def test_rejects_blacklisted_token(monkeypatch) -> None:
    user = _user()
    monkeypatch.setattr("app.api.websockets.Session", lambda _engine: _FakeSession(by_id={user.id: user}))

    async def _fake_blacklisted(_jti: str) -> bool:
        return True

    monkeypatch.setattr("app.api.websockets.is_token_blacklisted", _fake_blacklisted)
    token = create_access_token(str(user.id))

    assert await _authenticate_ws_token(token) is None


@pytest.mark.asyncio
async def test_rejects_unknown_user(monkeypatch) -> None:
    monkeypatch.setattr("app.api.websockets.Session", lambda _engine: _FakeSession(by_id={}))
    token = create_access_token(str(uuid.uuid4()))

    assert await _authenticate_ws_token(token) is None


@pytest.mark.asyncio
async def test_rejects_inactive_user(monkeypatch) -> None:
    user = _user(active=False)
    monkeypatch.setattr("app.api.websockets.Session", lambda _engine: _FakeSession(by_id={user.id: user}))
    token = create_access_token(str(user.id))

    assert await _authenticate_ws_token(token) is None


@pytest.mark.asyncio
async def test_accepts_valid_access_token(monkeypatch) -> None:
    user = _user()
    monkeypatch.setattr("app.api.websockets.Session", lambda _engine: _FakeSession(by_id={user.id: user}))
    token = create_access_token(str(user.id), expires_delta=timedelta(minutes=5))

    result = await _authenticate_ws_token(token)

    assert result is not None
    assert result.id == user.id
