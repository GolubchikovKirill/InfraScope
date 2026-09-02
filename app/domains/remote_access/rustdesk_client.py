"""Thin client for the self-hosted RustDesk console API (`lejianwen/rustdesk-api`).

InfraScope only *reads* status and *proxies* a small set of admin actions; it is
not the source of truth for the address book / users / audit log - the console
is. Paths follow the console's REST surface; if a future console version moves
them, adjust here (enable `show-swagger: 1` in its config.yaml to inspect).

Failures degrade softly: reads return empty, writes raise HTTPException(502) with
a clear message, so a console outage never takes InfraScope's own pages down.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import HTTPException

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


def _base() -> str:
    return settings.RUSTDESK_API_URL.rstrip("/")


def _headers() -> dict[str, str]:
    tok = settings.RUSTDESK_API_TOKEN.strip()
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=10.0)
    return _client


def enabled() -> bool:
    """True only when we can actually talk to the console (needs a token).

    The deploy pipeline works without this - it never calls the console - so the
    device grid still populates from InfraScope inventory when only the token is
    missing.
    """
    return bool(
        settings.REMOTE_ACCESS_ENABLED
        and settings.RUSTDESK_API_URL
        and settings.RUSTDESK_API_TOKEN.strip()
    )


async def _request(method: str, path: str, **kw: Any) -> httpx.Response:
    if not enabled():
        raise HTTPException(status_code=503, detail="remote access is disabled (REMOTE_ACCESS_ENABLED)")
    url = f"{_base()}{path}"
    try:
        resp = await _get_client().request(method, url, headers=_headers(), **kw)
    except httpx.HTTPError as exc:
        logger.warning("rustdesk-api %s %s failed: %s", method, path, exc)
        raise HTTPException(status_code=502, detail=f"RustDesk console unreachable: {exc}") from exc
    if resp.status_code == 401:
        raise HTTPException(status_code=502, detail="RustDesk console rejected the API token (set RUSTDESK_API_TOKEN)")
    return resp


def _data(resp: httpx.Response) -> Any:
    """Unwrap the console's {code, msg/message, data|rows|list} envelope.

    The admin API (/api/admin/*) nests the page as data.list / data.rows, so peel
    two levels; older client-API shapes put the list one level up.
    """
    try:
        body = resp.json()
    except ValueError:
        return None
    for _ in range(2):
        if isinstance(body, dict):
            for key in ("data", "rows", "list"):
                if key in body:
                    body = body[key]
                    break
            else:
                break
        else:
            break
    return body


# Paths for the lejianwen/rustdesk-api *admin* API, snapped from a live console
# (JS bundle at /_admin/, envelope {code,message,data}, 403 "Please log in first"
# without a token). If a console upgrade moves them, flip `show-swagger: 1` in the
# console's config.yaml and re-check.
_ADMIN = "/api/admin"


async def _list(path: str, page_size: int, **params: Any) -> list[dict[str, Any]]:
    resp = await _request("GET", path, params={"page": 1, "page_size": page_size, **params})
    rows = _data(resp) or []
    return rows if isinstance(rows, list) else []


# --------------------------------------------------------------------------- #
# reads                                                                      #
# --------------------------------------------------------------------------- #
async def list_peers() -> list[dict[str, Any]]:
    """Console device list - hostname/os/version/user/ip/last_online, auto-populated by clients."""
    return await _list(f"{_ADMIN}/peer/list", 2000)


async def list_connections(limit: int = 200) -> list[dict[str, Any]]:
    return await _list(f"{_ADMIN}/audit_conn/list", limit)


async def list_users() -> list[dict[str, Any]]:
    return await _list(f"{_ADMIN}/user/list", 500)


async def get_address_book() -> list[dict[str, Any]]:
    rows = await _list(f"{_ADMIN}/address_book/list", 2000)
    return rows


# --------------------------------------------------------------------------- #
# writes (proxied admin actions)                                             #
# --------------------------------------------------------------------------- #
async def upsert_address_book_entry(entry: dict[str, Any]) -> None:
    resp = await _request("POST", f"{_ADMIN}/address_book", json=entry)
    if resp.status_code not in (200, 201):
        raise HTTPException(status_code=502, detail=f"console rejected address-book upsert ({resp.status_code})")


async def delete_address_book_entry(peer_id: str) -> None:
    resp = await _request("DELETE", f"{_ADMIN}/address_book/{peer_id}")
    if resp.status_code not in (200, 204):
        raise HTTPException(status_code=502, detail=f"console rejected address-book delete ({resp.status_code})")
