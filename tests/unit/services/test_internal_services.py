import httpx
import pytest
from fastapi import HTTPException

from app.services import internal_services


class _DummyAsyncClient:
    def __init__(self, timeout: float):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def request(self, method: str, url: str, **kwargs):
        return await internal_services._REQUEST_HANDLER(method, url, **kwargs)


@pytest.mark.anyio
async def test_proxy_request_retries_safe_method_on_503(monkeypatch):
    calls = {"count": 0}

    async def _handler(method: str, url: str, **kwargs):
        calls["count"] += 1
        request = httpx.Request(method, url)
        if calls["count"] == 1:
            response = httpx.Response(503, request=request, text="temporary unavailable")
            raise httpx.HTTPStatusError("service unavailable", request=request, response=response)
        return httpx.Response(200, request=request, json={"ok": True})

    monkeypatch.setattr(internal_services, "_REQUEST_HANDLER", _handler, raising=False)
    monkeypatch.setattr(internal_services, "_http_client", None, raising=False)
    monkeypatch.setattr(internal_services.httpx, "AsyncClient", _DummyAsyncClient)
    monkeypatch.setattr(internal_services.settings, "INTERNAL_HTTP_RETRIES", 2, raising=False)
    monkeypatch.setattr(internal_services.settings, "INTERNAL_HTTP_RETRY_BACKOFF_SECONDS", 0.0, raising=False)

    payload = await internal_services._proxy_request(
        base_url="http://svc:8010",
        method="GET",
        path="/health",
    )

    assert payload == {"ok": True}
    assert calls["count"] == 2


@pytest.mark.anyio
async def test_proxy_request_does_not_retry_post_by_default(monkeypatch):
    calls = {"count": 0}

    async def _handler(method: str, url: str, **kwargs):
        calls["count"] += 1
        request = httpx.Request(method, url)
        raise httpx.ConnectTimeout("timeout", request=request)

    monkeypatch.setattr(internal_services, "_REQUEST_HANDLER", _handler, raising=False)
    monkeypatch.setattr(internal_services, "_http_client", None, raising=False)
    monkeypatch.setattr(internal_services.httpx, "AsyncClient", _DummyAsyncClient)
    monkeypatch.setattr(internal_services.settings, "INTERNAL_HTTP_RETRIES", 5, raising=False)
    monkeypatch.setattr(internal_services.settings, "INTERNAL_HTTP_RETRY_BACKOFF_SECONDS", 0.0, raising=False)

    with pytest.raises(HTTPException):
        await internal_services._proxy_request(
            base_url="http://svc:8010",
            method="POST",
            path="/run",
            json_body={"x": 1},
        )

    assert calls["count"] == 1
