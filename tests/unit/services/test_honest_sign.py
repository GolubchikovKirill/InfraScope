from __future__ import annotations

import httpx
import pytest

from app.core.config import settings
from app.services import honest_sign


def _configure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "HONEST_SIGN_TARGETS", "172.23.8.21|Первая,172.23.8.36|XP касса")
    monkeypatch.setattr(settings, "HONEST_SIGN_API_LOGIN", "user")
    monkeypatch.setattr(settings, "HONEST_SIGN_API_PASSWORD", "password")
    monkeypatch.setattr(settings, "HONEST_SIGN_TOKEN", "00000000-0000-4000-8000-000000000001")
    monkeypatch.setattr(settings, "HONEST_SIGN_STATUS_WAIT_SECONDS", 0)


def test_configured_targets_normalizes_ipv4_and_labels() -> None:
    targets = honest_sign.configured_targets(
        "172.23.8.21|Первая, 172.23.8.21|Дубликат,invalid,172.23.8.36"
    )

    assert [(target.host, target.label) for target in targets] == [
        ("172.23.8.21", "Первая"),
        ("172.23.8.36", "Касса"),
    ]


@pytest.mark.asyncio
async def test_check_all_reports_ready_and_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "172.23.8.21":
            return httpx.Response(200, json={"status": "ready", "version": "2.5.1"})
        raise httpx.ConnectError("offline", request=request)

    monkeypatch.setattr(
        honest_sign,
        "_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=1),
    )

    rows = await honest_sign.check_all_honest_sign_targets()

    assert rows[0].ready is True
    assert rows[0].version == "2.5.1"
    assert rows[1].reachable is False
    assert rows[1].status == "ERROR"


@pytest.mark.asyncio
async def test_initialize_skips_module_that_is_already_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(200, json={"status": "ready", "version": "2.5.1"})

    monkeypatch.setattr(
        honest_sign,
        "_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=1),
    )

    result = await honest_sign.initialize_honest_sign_target(honest_sign.configured_targets()[0])

    assert result.result == "ALREADY_READY"
    assert methods == ["GET"]
