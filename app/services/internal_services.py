from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

from app.core.config import settings
from app.observability.metrics import observe_service_edge

_SAFE_RETRY_METHODS = {"GET", "HEAD", "OPTIONS"}
_RETRYABLE_STATUS_CODES = {502, 503, 504}
_http_client: httpx.AsyncClient | None = None


def _raise_proxy_http_error(*, status_code: int, kind: str, code: str, detail: str) -> None:
    raise HTTPException(
        status_code=status_code,
        detail={
            "kind": kind,
            "code": code,
            "detail": detail,
        },
    )


def _get_http_client(timeout: float) -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=timeout)
    return _http_client


def _headers() -> dict[str, str]:
    if settings.INTERNAL_SERVICE_TOKEN:
        return {"X-Internal-Token": settings.INTERNAL_SERVICE_TOKEN}
    return {}


async def _proxy_request(
    *,
    base_url: str,
    method: str,
    path: str,
    timeout: float | None = None,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    target = (urlparse(base_url).hostname or "unknown").strip() or "unknown"
    normalized_method = method.upper().strip()
    request_timeout = timeout if timeout is not None else settings.INTERNAL_HTTP_TIMEOUT_SECONDS
    retries = settings.INTERNAL_HTTP_RETRIES if normalized_method in _SAFE_RETRY_METHODS else 0
    backoff = max(settings.INTERNAL_HTTP_RETRY_BACKOFF_SECONDS, 0.0)
    attempts = max(0, retries) + 1

    for attempt in range(1, attempts + 1):
        try:
            with observe_service_edge(
                source="backend",
                target=target,
                transport="http",
                operation=f"{normalized_method} {path}",
            ):
                client = _get_http_client(request_timeout)
                response = await client.request(
                    method=normalized_method,
                    url=url,
                    params=params,
                    json=json_body,
                    data=data,
                    files=files,
                    headers=_headers(),
                    timeout=request_timeout,
                )
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                return data
            _raise_proxy_http_error(
                status_code=502,
                kind="integration",
                code="invalid_payload",
                detail="internal service returned invalid payload",
            )
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else None
            should_retry = status in _RETRYABLE_STATUS_CODES and attempt < attempts
            if should_retry:
                await asyncio.sleep(backoff * attempt)
                continue
            detail = exc.response.text if exc.response is not None else "internal service status error"
            mapped_status = status if status in {400, 401, 403, 404, 409, 422} else 502
            _raise_proxy_http_error(
                status_code=mapped_status,
                kind="integration",
                code=f"http_{status or 'unknown'}",
                detail=detail,
            )
        except httpx.HTTPError as exc:
            if attempt < attempts:
                await asyncio.sleep(backoff * attempt)
                continue
            _raise_proxy_http_error(
                status_code=504,
                kind="timeout",
                code="unavailable",
                detail=f"internal service unavailable: {exc}",
            )
    _raise_proxy_http_error(
        status_code=504,
        kind="timeout",
        code="unavailable",
        detail="internal service unavailable",
    )


async def maybe_proxy(
    *,
    enabled: bool,
    call: Callable[[], Any],
) -> Any:
    if enabled:
        return await call()
    return None
