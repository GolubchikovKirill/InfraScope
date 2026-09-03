"""Client for the self-hosted RustDesk console API (`lejianwen/rustdesk-api`).

The console exposes two API surfaces backed by the *same* token row in its
`user_tokens` table, and they differ only in which header they read:

    /api/*        middleware.RustAuth()        -> Authorization: Bearer <token>
    /api/admin/*  middleware.BackendUserAuth() -> api-token: <token>

So every request here sends both headers, and one token unlocks everything:
console accounts, shared address books, the peer inventory (which, unlike the
client API's `/api/peers`, carries the installed client `version`) and the
connection audit log.

Token lifecycle: `RUSTDESK_API_TOKEN` is used when set. Otherwise - or after the
console rejects it - we mint a fresh one with `POST /api/admin/login` under
`RUSTDESK_ADMIN_USERNAME`. The console's `Login()` *adds* a token row rather
than replacing it, so an operator logging into the web console does not evict
ours.

Failures degrade softly: reads return empty, writes raise HTTPException(502)
with the console's own message, so a console outage never takes InfraScope's
pages down.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from fastapi import HTTPException

from app.core.config import settings

logger = logging.getLogger(__name__)

# console user status codes (model.StatusCode)
STATUS_ENABLED = 1
STATUS_DISABLED = 2

# address-book collection rule (model/addressBook.go)
RULE_TYPE_USER = 1
RULE_TYPE_GROUP = 2
RULE_READ = 1
RULE_READ_WRITE = 2
RULE_FULL = 3

# console group type
GROUP_TYPE_DEFAULT = 1
GROUP_TYPE_SHARED = 2

# cached token minted from RUSTDESK_ADMIN_USERNAME/PASSWORD; cleared on 401/403
_minted_token: str | None = None


def _base() -> str:
    return settings.RUSTDESK_API_URL.rstrip("/")


def _configured_token() -> str:
    return settings.RUSTDESK_API_TOKEN.strip()


def _can_login() -> bool:
    return bool(settings.RUSTDESK_ADMIN_USERNAME.strip() and settings.RUSTDESK_ADMIN_PASSWORD)


def enabled() -> bool:
    """True only when we can actually talk to the console.

    Needs either a preset token or service credentials to mint one. The deploy
    pipeline works without this - it never calls the console - so the device grid
    still populates from InfraScope inventory when only the token is missing.
    """
    return bool(
        settings.REMOTE_ACCESS_ENABLED
        and settings.RUSTDESK_API_URL
        and (_configured_token() or _can_login())
    )


def reset_token_cache() -> None:
    """Drop the minted token so the next call logs in again (tests + 401 retry)."""
    global _minted_token
    _minted_token = None


async def _login() -> str:
    """Mint a console token under the service account."""
    url = f"{_base()}/api/admin/login"
    payload = {
        "username": settings.RUSTDESK_ADMIN_USERNAME.strip(),
        "password": settings.RUSTDESK_ADMIN_PASSWORD,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"RustDesk console unreachable: {exc}") from exc
    body = _envelope(resp)
    token = (body or {}).get("token") if isinstance(body, dict) else None
    if not token:
        raise HTTPException(
            status_code=502,
            detail=f"RustDesk console login failed ({resp.status_code}: {resp.text[:200]})",
        )
    return str(token)


async def _token() -> str:
    global _minted_token
    preset = _configured_token()
    if preset:
        return preset
    if _minted_token:
        return _minted_token
    if not _can_login():
        raise HTTPException(
            status_code=503,
            detail="RustDesk console has no credentials (set RUSTDESK_API_TOKEN or RUSTDESK_ADMIN_USERNAME/PASSWORD)",
        )
    _minted_token = await _login()
    return _minted_token


def _headers(token: str) -> dict[str, str]:
    # both surfaces, one token - see the module docstring
    return {"Authorization": f"Bearer {token}", "api-token": token}


async def _request(method: str, path: str, **kw: Any) -> httpx.Response:
    """One console call, retried once against a freshly minted token on 401/403.

    A fresh client per call on purpose: the worker runs each sync in its own
    `asyncio.run()`, so a cached AsyncClient would outlive its event loop
    ("Event loop is closed").
    """
    global _minted_token
    if not enabled():
        raise HTTPException(status_code=503, detail="remote access is disabled (REMOTE_ACCESS_ENABLED)")
    url = f"{_base()}{path}"

    async def _send(token: str) -> httpx.Response:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                return await client.request(method, url, headers=_headers(token), **kw)
        except httpx.HTTPError as exc:
            logger.warning("rustdesk-api %s %s failed: %s", method, path, exc)
            raise HTTPException(status_code=502, detail=f"RustDesk console unreachable: {exc}") from exc

    resp = await _send(await _token())
    if resp.status_code in (401, 403) and not _configured_token() and _can_login():
        # the minted token was revoked or expired - one retry with a new one
        _minted_token = None
        resp = await _send(await _token())
    if resp.status_code in (401, 403):
        raise HTTPException(
            status_code=502,
            detail="RustDesk console rejected the API token (set RUSTDESK_API_TOKEN or the service account)",
        )
    return resp


def _envelope(resp: httpx.Response) -> Any:
    """Unwrap one level of the console's response envelope.

    Client API : {"total": N, "data": [...]}   or  {"data": "<json string>"}
    Admin  API : {"code": 0, "data": {"list": [...], "total": N}}
    """
    try:
        body = resp.json()
    except ValueError:
        return None
    if isinstance(body, dict):
        for key in ("data", "rows", "list"):
            if key in body:
                return body[key]
    return body


def _rows(resp: httpx.Response) -> list[dict[str, Any]]:
    """Rows out of either envelope shape; anything unexpected reads as empty."""
    data = _envelope(resp)
    if isinstance(data, dict):
        data = data.get("list") or data.get("data") or []
    if not isinstance(data, list):
        return []
    return [r for r in data if isinstance(r, dict)]


async def _list(path: str, page_size: int, **params: Any) -> list[dict[str, Any]]:
    """GET a paged list endpoint; tolerate a missing endpoint (older console) as []."""
    query = {"page": 1, "page_size": page_size, "current": 1, "pageSize": page_size}
    query.update({k: v for k, v in params.items() if v is not None})
    resp = await _request("GET", path, params=query)
    if resp.status_code == 404:
        return []
    return _rows(resp)


def _check_write(resp: httpx.Response, what: str) -> Any:
    """Console writes answer 200 with `code != 0` on failure - surface the message."""
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502, detail=f"console rejected {what} ({resp.status_code}: {resp.text[:200]})"
        )
    try:
        body = resp.json()
    except ValueError:
        return None
    if isinstance(body, dict) and body.get("code") not in (None, 0):
        raise HTTPException(status_code=502, detail=f"console rejected {what}: {body.get('msg') or body}")
    return body.get("data") if isinstance(body, dict) else body


# --------------------------------------------------------------------------- #
# peers / audit (admin API - richer than the client API's /api/peers)         #
# --------------------------------------------------------------------------- #
async def list_admin_peers() -> list[dict[str, Any]]:
    """Every device the console has ever registered.

    Carries `version`, `os`, `hostname`, `username`, `last_online_time`,
    `last_online_ip` - the client API's `/api/peers` has none of those.
    """
    return await _list("/api/admin/peer/list", 2000)


async def list_peers() -> list[dict[str, Any]]:
    """Client-API peer list: id + info{device_name, os, username} + status."""
    return await _list("/api/peers", 2000)


async def list_users() -> list[dict[str, Any]]:
    return await _list("/api/users", 500)


async def list_connections(limit: int = 200) -> list[dict[str, Any]]:
    """Connection audit log (admin API; the client API has no read endpoint)."""
    return await _list("/api/admin/audit_conn/list", limit)


# --------------------------------------------------------------------------- #
# console accounts                                                            #
# --------------------------------------------------------------------------- #
async def current_console_user() -> dict[str, Any]:
    """The account our token belongs to.

    Verified live against the prod console: this response carries `username`,
    `email`, `nickname`, a fresh `token` and `route_names` - no numeric `id`.
    That id only appears on rows from `/user/list`, so callers that need it
    (address-book ownership) should use `current_console_user_id()` instead.
    """
    resp = await _request("GET", "/api/admin/user/current")
    data = _envelope(resp)
    return data if isinstance(data, dict) else {}


async def current_console_user_id() -> int:
    """Numeric id of the account our token belongs to.

    `/user/current` doesn't carry one (see `current_console_user`), so this
    resolves it by matching `username` against `/user/list`.
    """
    me = await current_console_user()
    username = str(me.get("username") or "").strip()
    if not username:
        return 0
    for user in await list_console_users():
        if str(user.get("username") or "").strip() == username:
            return int(user.get("id") or 0)
    return 0


async def list_console_users() -> list[dict[str, Any]]:
    return await _list("/api/admin/user/list", 500)


async def create_console_user(
    *, username: str, group_id: int, is_admin: bool = False, email: str = "", nickname: str = ""
) -> None:
    """Create a console account. The password is a separate call - `UserForm`
    carries no password field (see `http/request/admin/user.go`)."""
    body = {
        "username": username,
        "group_id": group_id,
        "is_admin": is_admin,
        "status": STATUS_ENABLED,
        "email": email,
        "nickname": nickname or username,
    }
    _check_write(await _request("POST", "/api/admin/user/create", json=body), "user create")


async def set_console_user_password(user_id: int, password: str) -> None:
    # the bound route is /changePwd (UserBind in http/router/admin.go) even
    # though the Go handler is named UpdatePassword and the generated swagger
    # docs advertise /updatePassword - verified live against the prod console,
    # which 404s on /updatePassword.
    _check_write(
        await _request("POST", "/api/admin/user/changePwd", json={"id": user_id, "password": password}),
        "user password",
    )


async def update_console_user(
    *,
    user_id: int,
    username: str,
    group_id: int,
    is_admin: bool,
    status: int,
    email: str = "",
    nickname: str = "",
) -> None:
    """Full-record update - the console's UserForm replaces, it does not merge."""
    body = {
        "id": user_id,
        "username": username,
        "group_id": group_id,
        "is_admin": is_admin,
        "status": status,
        "email": email,
        "nickname": nickname or username,
    }
    _check_write(await _request("POST", "/api/admin/user/update", json=body), "user update")


# --------------------------------------------------------------------------- #
# groups                                                                      #
# --------------------------------------------------------------------------- #
async def list_groups() -> list[dict[str, Any]]:
    return await _list("/api/admin/group/list", 200)


async def create_group(name: str, group_type: int = GROUP_TYPE_SHARED) -> None:
    _check_write(
        await _request("POST", "/api/admin/group/create", json={"name": name, "type": group_type}),
        "group create",
    )


# --------------------------------------------------------------------------- #
# shared address-book collections                                             #
# --------------------------------------------------------------------------- #
async def list_collections() -> list[dict[str, Any]]:
    return await _list("/api/admin/address_book_collection/list", 200)


async def create_collection(name: str, user_id: int) -> None:
    _check_write(
        await _request(
            "POST", "/api/admin/address_book_collection/create", json={"name": name, "user_id": user_id}
        ),
        "collection create",
    )


async def list_collection_rules(collection_id: int) -> list[dict[str, Any]]:
    return await _list("/api/admin/address_book_collection_rule/list", 500, collection_id=collection_id)


async def create_collection_rule(
    *, collection_id: int, owner_id: int, to_id: int, rule_type: int = RULE_TYPE_GROUP, rule: int = RULE_READ
) -> None:
    # CheckForm (http/controller/admin/addressBookCollectionRule.go) rejects the
    # write with a bare "Params validation failed." - no field name - unless
    # user_id is the collection's owner; verified live against the prod console.
    body = {
        "user_id": owner_id,
        "collection_id": collection_id,
        "to_id": to_id,
        "type": rule_type,
        "rule": rule,
    }
    _check_write(
        await _request("POST", "/api/admin/address_book_collection_rule/create", json=body), "share rule"
    )


# --------------------------------------------------------------------------- #
# address-book rows (admin API - the only path that reaches a shared book)     #
# --------------------------------------------------------------------------- #
async def list_address_book_rows(*, user_id: int, collection_id: int) -> list[dict[str, Any]]:
    return await _list(
        "/api/admin/address_book/list", 2000, user_id=user_id, collection_id=collection_id
    )


async def create_address_book_row(payload: dict[str, Any]) -> None:
    _check_write(await _request("POST", "/api/admin/address_book/create", json=payload), "address-book add")


async def update_address_book_row(payload: dict[str, Any]) -> None:
    _check_write(
        await _request("POST", "/api/admin/address_book/update", json=payload), "address-book update"
    )


async def delete_address_book_row(*, row_id: int, peer_id: str) -> None:
    """Remove one shared-book row.

    Both fields are required: the handler keys off `row_id`, but the form it
    binds still validates `id` as mandatory, so sending only `row_id` is rejected.
    """
    _check_write(
        await _request("POST", "/api/admin/address_book/delete", json={"row_id": row_id, "id": peer_id}),
        "address-book delete",
    )


# --------------------------------------------------------------------------- #
# personal address book (client API) - kept for the legacy `admin` book        #
# --------------------------------------------------------------------------- #
def _parse_ab(body: Any) -> dict[str, Any]:
    """`/api/ab` returns {"data": "<json string of {tags, peers}>"} - peel it."""
    raw = body.get("data") if isinstance(body, dict) else body
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "{}")
        except ValueError:
            raw = {}
    return raw if isinstance(raw, dict) else {}


async def get_address_book() -> list[dict[str, Any]]:
    resp = await _request("GET", "/api/ab")
    try:
        ab = _parse_ab(resp.json())
    except ValueError:
        return []
    peers = ab.get("peers")
    return peers if isinstance(peers, list) else []
