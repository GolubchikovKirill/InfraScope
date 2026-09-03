"""The console client's two load-bearing behaviours.

The console exposes the same token on two API surfaces that read *different*
headers (`Authorization: Bearer` for `/api/*`, `api-token` for `/api/admin/*`),
and it wraps admin responses in an extra envelope. Getting either wrong looks
exactly like "the admin API is not available", which is the wrong conclusion
this module exists to prevent.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.domains.remote_access import rustdesk_client


@pytest.fixture(autouse=True)
def _console_enabled(monkeypatch):
    monkeypatch.setattr(settings, "REMOTE_ACCESS_ENABLED", True)
    monkeypatch.setattr(settings, "RUSTDESK_API_URL", "http://console:21114")
    monkeypatch.setattr(settings, "RUSTDESK_API_TOKEN", "")
    monkeypatch.setattr(settings, "RUSTDESK_ADMIN_USERNAME", "")
    monkeypatch.setattr(settings, "RUSTDESK_ADMIN_PASSWORD", "")
    rustdesk_client.reset_token_cache()
    yield
    rustdesk_client.reset_token_cache()


_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _mock(monkeypatch, handler) -> None:
    # `rustdesk_client.httpx` is the module itself, so capture the real class
    # before patching or the factory recurses into itself
    monkeypatch.setattr(
        rustdesk_client.httpx,
        "AsyncClient",
        lambda **kw: _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler), timeout=1),
    )


def test_every_call_carries_both_auth_headers(monkeypatch) -> None:
    monkeypatch.setattr(settings, "RUSTDESK_API_TOKEN", "tok-1")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"code": 0, "data": {"list": [], "total": 0}})

    _mock(monkeypatch, handler)
    asyncio.run(rustdesk_client.list_admin_peers())

    assert seen[0].headers["authorization"] == "Bearer tok-1"
    assert seen[0].headers["api-token"] == "tok-1"


def test_admin_envelope_is_unwrapped_to_rows(monkeypatch) -> None:
    monkeypatch.setattr(settings, "RUSTDESK_API_TOKEN", "tok-1")

    def handler(request: httpx.Request) -> httpx.Response:
        # /api/admin/* wraps its list one level deeper than the client API
        return httpx.Response(
            200,
            json={"code": 0, "data": {"list": [{"id": "VNK_MGR_D1", "version": "1.4.9"}], "total": 1}},
        )

    _mock(monkeypatch, handler)
    rows = asyncio.run(rustdesk_client.list_admin_peers())
    assert rows == [{"id": "VNK_MGR_D1", "version": "1.4.9"}]


def test_client_envelope_is_unwrapped_to_rows(monkeypatch) -> None:
    monkeypatch.setattr(settings, "RUSTDESK_API_TOKEN", "tok-1")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"total": 1, "data": [{"id": "VNK_MGR_D1"}]})

    _mock(monkeypatch, handler)
    assert asyncio.run(rustdesk_client.list_peers()) == [{"id": "VNK_MGR_D1"}]


def test_a_revoked_minted_token_is_reminted_once(monkeypatch) -> None:
    monkeypatch.setattr(settings, "RUSTDESK_ADMIN_USERNAME", "infrascope")
    monkeypatch.setattr(settings, "RUSTDESK_ADMIN_PASSWORD", "pw")
    calls: list[str] = []
    logins = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal logins
        if request.url.path == "/api/admin/login":
            logins += 1
            calls.append("login")
            return httpx.Response(200, json={"code": 0, "data": {"token": f"tok-{logins}"}})
        calls.append(request.headers.get("api-token", "?"))
        # the first token is stale; the freshly minted one works
        if request.headers.get("api-token") == "tok-1":
            return httpx.Response(401, json={"error": "Unauthorized"})
        return httpx.Response(200, json={"code": 0, "data": {"list": [{"id": "x"}], "total": 1}})

    _mock(monkeypatch, handler)
    assert asyncio.run(rustdesk_client.list_admin_peers()) == [{"id": "x"}]
    assert calls == ["login", "tok-1", "login", "tok-2"]


def test_a_permanently_rejected_token_surfaces_as_502(monkeypatch) -> None:
    monkeypatch.setattr(settings, "RUSTDESK_API_TOKEN", "tok-dead")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"code": 403, "msg": "NeedLogin"})

    _mock(monkeypatch, handler)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(rustdesk_client.list_admin_peers())
    assert exc.value.status_code == 502
    assert "token" in exc.value.detail


def test_a_write_that_answers_200_with_an_error_code_still_fails(monkeypatch) -> None:
    """The console reports write failures inside a 200 body - a bare status check
    would silently swallow "ItemExists" and friends."""
    monkeypatch.setattr(settings, "RUSTDESK_API_TOKEN", "tok-1")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 101, "msg": "ItemExists"})

    _mock(monkeypatch, handler)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(rustdesk_client.create_address_book_row({"id": "X"}))
    assert exc.value.status_code == 502 and "ItemExists" in exc.value.detail


def test_create_console_user_sends_the_fields_the_console_validates(monkeypatch) -> None:
    """`admin.UserForm` requires username, group_id and status, and carries no
    password field at all - the password is a separate call."""
    monkeypatch.setattr(settings, "RUSTDESK_API_TOKEN", "tok-1")
    bodies: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content)
        return httpx.Response(200, json={"code": 0, "data": None})

    _mock(monkeypatch, handler)
    asyncio.run(
        rustdesk_client.create_console_user(username="ivanov", group_id=3, is_admin=False)
    )
    import json

    body = json.loads(bodies[0])
    assert body["username"] == "ivanov" and body["group_id"] == 3
    assert body["status"] == rustdesk_client.STATUS_ENABLED
    assert "password" not in body


def test_console_is_disabled_without_a_token_or_credentials(monkeypatch) -> None:
    assert rustdesk_client.enabled() is False
    monkeypatch.setattr(settings, "RUSTDESK_API_TOKEN", "tok-1")
    assert rustdesk_client.enabled() is True


def test_set_console_user_password_hits_changepwd_not_updatepassword(monkeypatch) -> None:
    """The bound route is /changePwd (UserBind in http/router/admin.go) even
    though the Go handler is UpdatePassword and the generated swagger docs
    advertise /updatePassword - verified live against the prod console, which
    404s on /updatePassword. Locking the exact path down here since the fake
    console in test_remote_access_console.py stubs this call out entirely and
    would not have caught the mismatch."""
    monkeypatch.setattr(settings, "RUSTDESK_API_TOKEN", "tok-1")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"code": 0, "data": None})

    _mock(monkeypatch, handler)
    asyncio.run(rustdesk_client.set_console_user_password(2, "s3cret"))

    assert seen[0].url.path == "/api/admin/user/changePwd"


def test_current_console_user_has_no_id_only_list_rows_do(monkeypatch) -> None:
    """`/user/current` returns {username, email, avatar, token, route_names,
    nickname} - no numeric id, verified live against the prod console. Only
    `/user/list` rows carry `id`. current_console_user_id() must resolve it
    by matching username against the list, not by reading `me["id"]`."""
    monkeypatch.setattr(settings, "RUSTDESK_API_TOKEN", "tok-1")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/admin/user/current":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {"username": "infrascope", "email": "", "nickname": "svc"},
                },
            )
        assert request.url.path == "/api/admin/user/list"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "list": [
                        {"id": 1, "username": "admin"},
                        {"id": 2, "username": "infrascope"},
                    ],
                    "total": 2,
                },
            },
        )

    _mock(monkeypatch, handler)
    assert asyncio.run(rustdesk_client.current_console_user_id()) == 2


def test_current_console_user_id_is_zero_when_username_is_unlisted(monkeypatch) -> None:
    monkeypatch.setattr(settings, "RUSTDESK_API_TOKEN", "tok-1")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/admin/user/current":
            return httpx.Response(200, json={"code": 0, "data": {"username": "ghost"}})
        return httpx.Response(200, json={"code": 0, "data": {"list": [], "total": 0}})

    _mock(monkeypatch, handler)
    assert asyncio.run(rustdesk_client.current_console_user_id()) == 0


def test_create_collection_rule_sends_the_owner_id_the_console_requires(monkeypatch) -> None:
    """The console's CheckForm rejects the write with a bare "Params validation
    failed." (no field name) unless user_id names the collection's actual
    owner - verified live against the prod console."""
    monkeypatch.setattr(settings, "RUSTDESK_API_TOKEN", "tok-1")
    bodies: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content)
        return httpx.Response(200, json={"code": 0, "data": None})

    _mock(monkeypatch, handler)
    asyncio.run(
        rustdesk_client.create_collection_rule(collection_id=1, owner_id=1, to_id=3)
    )
    import json

    body = json.loads(bodies[0])
    assert body == {"user_id": 1, "collection_id": 1, "to_id": 3, "type": rustdesk_client.RULE_TYPE_GROUP, "rule": rustdesk_client.RULE_READ}
