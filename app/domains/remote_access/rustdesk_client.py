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


def _base() -> str:
    return settings.RUSTDESK_API_URL.rstrip("/")


def _headers() -> dict[str, str]:
    tok = settings.RUSTDESK_API_TOKEN.strip()
    return {"Authorization": f"Bearer {tok}"} if tok else {}


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
    # fresh client per call: the worker runs each sync in its own asyncio.run(),
    # so a cached AsyncClient would outlive its event loop ("Event loop is closed")
    if not enabled():
        raise HTTPException(status_code=503, detail="remote access is disabled (REMOTE_ACCESS_ENABLED)")
    url = f"{_base()}{path}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.request(method, url, headers=_headers(), **kw)
    except httpx.HTTPError as exc:
        logger.warning("rustdesk-api %s %s failed: %s", method, path, exc)
        raise HTTPException(status_code=502, detail=f"RustDesk console unreachable: {exc}") from exc
    if resp.status_code == 401:
        raise HTTPException(status_code=502, detail="RustDesk console rejected the API token (set RUSTDESK_API_TOKEN)")
    return resp


def _data(resp: httpx.Response) -> Any:
    """Unwrap the lejianwen client-API envelope.

    Reads verified against a live console with a `POST /api/login` JWT:
      /api/peers  -> {"total": N, "data": [ {id, info:{device_name,os,username}, ...} ]}
      /api/users  -> {"total": N, "data": [ {name, email, is_admin, ...} ]}
      /api/ab     -> {"data": "<json string of {tags:[...], peers:[...]}>"}
    So: one level of data/rows/list; address book is peeled separately.
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


async def _list(path: str, page_size: int) -> list[dict[str, Any]]:
    """GET a paged list endpoint; tolerate a missing endpoint (older console) as []."""
    try:
        resp = await _request("GET", path, params={"page": 1, "page_size": page_size, "current": 1})
    except HTTPException:
        raise
    if resp.status_code == 404:
        return []
    rows = _data(resp) or []
    return rows if isinstance(rows, list) else []


# --------------------------------------------------------------------------- #
# reads (client API - a POST /api/login JWT unlocks these; /api/admin/* needs
#        the web-panel's own session and is NOT reachable with that token)    #
# --------------------------------------------------------------------------- #
async def list_peers() -> list[dict[str, Any]]:
    """Auto-populated device list: id + info{device_name,os,username} + last_online."""
    return await _list("/api/peers", 2000)


async def list_users() -> list[dict[str, Any]]:
    return await _list("/api/users", 500)


async def list_connections(limit: int = 200) -> list[dict[str, Any]]:
    # the connection audit log is admin-panel-only; no client-API endpoint exists
    return await _list("/api/audit/conn", limit)


def _parse_ab(body: Any) -> dict[str, Any]:
    """`/api/ab` returns {"data": "<json string of {tags, peers}>"} - peel it."""
    import json

    raw = body.get("data") if isinstance(body, dict) else body
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "{}")
        except ValueError:
            raw = {}
    return raw if isinstance(raw, dict) else {}


async def _get_ab_raw() -> dict[str, Any]:
    resp = await _request("GET", "/api/ab")
    try:
        return _parse_ab(resp.json())
    except ValueError:
        return {}


async def get_address_book() -> list[dict[str, Any]]:
    ab = await _get_ab_raw()
    peers = ab.get("peers")
    return peers if isinstance(peers, list) else []


# --------------------------------------------------------------------------- #
# writes - lejianwen legacy address book is a single per-user blob:           #
# POST /api/ab {"data": "<json string of {tags, peers}>"} (read-modify-write) #
# --------------------------------------------------------------------------- #
_AB_PEER_FIELDS = ("id", "username", "password", "hostname", "alias", "platform", "tags", "forceAlwaysRelay")


def _slim_peer(p: dict[str, Any]) -> dict[str, Any]:
    return {k: p[k] for k in _AB_PEER_FIELDS if k in p}


async def _put_ab(tags: list, peers: list) -> None:
    import json

    payload = {"data": json.dumps({"tags": tags, "peers": peers}, ensure_ascii=False)}
    resp = await _request("POST", "/api/ab", json=payload)
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"console rejected address-book write ({resp.status_code}: {resp.text[:200]})",
        )


async def upsert_address_book_entries(entries: list[dict[str, Any]]) -> None:
    """One read-modify-write for a batch of peers (keyed by id)."""
    ab = await _get_ab_raw()
    by_id = {p["id"]: _slim_peer(p) for p in ab.get("peers", []) if isinstance(p, dict) and p.get("id")}
    tags = list(ab.get("tags", []))
    for entry in entries:
        new = _slim_peer(entry)
        if not new.get("id"):
            continue
        by_id[new["id"]] = new
        for t in new.get("tags", []) or []:
            if t and t not in tags:
                tags.append(t)
    await _put_ab(tags, list(by_id.values()))


async def upsert_address_book_entry(entry: dict[str, Any]) -> None:
    await upsert_address_book_entries([entry])


async def delete_address_book_entry(peer_id: str) -> None:
    ab = await _get_ab_raw()
    peers = [_slim_peer(p) for p in ab.get("peers", []) if isinstance(p, dict) and p.get("id") != peer_id]
    await _put_ab(list(ab.get("tags", [])), peers)
