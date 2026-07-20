from __future__ import annotations

from datetime import UTC, datetime

from app.api.routes import honest_sign as honest_sign_routes
from app.core.config import settings
from app.domains.integrations.schemas import HonestSignInitializePublic, HonestSignStatusPublic


def test_honest_sign_rejects_unlisted_account(client, user_token: str):
    response = client.get(
        "/api/v1/honest-sign/targets",
        headers={"Authorization": f"Bearer {user_token}"},
    )

    assert response.status_code == 403


def test_honest_sign_operator_can_check_targets(client, admin_token: str, monkeypatch):
    monkeypatch.setattr(settings, "HONEST_SIGN_ALLOWED_EMAILS", "admin@example.com")
    monkeypatch.setattr(settings, "HONEST_SIGN_TARGETS", "172.23.8.21|Касса")
    monkeypatch.setattr(settings, "HONEST_SIGN_API_LOGIN", "user")
    monkeypatch.setattr(settings, "HONEST_SIGN_API_PASSWORD", "password")

    async def fake_check_all():
        return [
            HonestSignStatusPublic(
                host="172.23.8.21",
                label="Касса",
                reachable=True,
                status="ready",
                version="2.5.1",
                ready=True,
                checked_at=datetime.now(UTC).isoformat(),
            )
        ]

    monkeypatch.setattr(honest_sign_routes, "check_all_honest_sign_targets", fake_check_all)
    response = client.post(
        "/api/v1/honest-sign/check-all",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    assert response.json()["data"][0]["ready"] is True


def test_honest_sign_initialization_is_logged(client, admin_token: str, monkeypatch):
    monkeypatch.setattr(settings, "HONEST_SIGN_ALLOWED_EMAILS", "admin@example.com")
    monkeypatch.setattr(settings, "HONEST_SIGN_TARGETS", "172.23.8.21|Касса")

    async def fake_initialize(target):
        return HonestSignInitializePublic(
            host=target.host,
            label=target.label,
            initial_status="not_initialized",
            final_status="ready",
            result="READY",
            message="Статус после запроса: ready",
            checked_at=datetime.now(UTC).isoformat(),
        )

    monkeypatch.setattr(honest_sign_routes, "initialize_honest_sign_target", fake_initialize)
    response = client.post(
        "/api/v1/honest-sign/172.23.8.21/initialize",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    assert response.json()["result"] == "READY"
