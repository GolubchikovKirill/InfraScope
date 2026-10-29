from __future__ import annotations

from datetime import UTC, datetime

from app.api.routes import honest_sign as honest_sign_routes
from app.core.config import settings
from app.domains.integrations.schemas import HonestSignInitializePublic, HonestSignStatusPublic
from app.domains.operations.models import CashRegister
from app.services.honest_sign import record_check_results


def test_honest_sign_targets_visible_to_any_authenticated_user(client, user_token: str, monkeypatch):
    monkeypatch.setattr(settings, "HONEST_SIGN_TARGETS", "172.23.8.21|Касса")
    monkeypatch.setattr(settings, "HONEST_SIGN_API_LOGIN", "user")
    monkeypatch.setattr(settings, "HONEST_SIGN_API_PASSWORD", "password")

    response = client.get(
        "/api/v1/honest-sign/targets",
        headers={"Authorization": f"Bearer {user_token}"},
    )

    assert response.status_code == 200
    assert response.json()["data"][0]["host"] == "172.23.8.21"


def test_honest_sign_initialize_requires_superuser(client, user_token: str, monkeypatch):
    monkeypatch.setattr(settings, "HONEST_SIGN_TARGETS", "172.23.8.21|Касса")

    response = client.post(
        "/api/v1/honest-sign/172.23.8.21/initialize",
        headers={"Authorization": f"Bearer {user_token}"},
    )

    assert response.status_code == 403


def test_honest_sign_can_check_targets(client, admin_token: str, monkeypatch):
    monkeypatch.setattr(settings, "HONEST_SIGN_TARGETS", "172.23.8.21|Касса")
    monkeypatch.setattr(settings, "HONEST_SIGN_API_LOGIN", "user")
    monkeypatch.setattr(settings, "HONEST_SIGN_API_PASSWORD", "password")

    async def fake_check_all(session=None):
        return [
            HonestSignStatusPublic(
                host="172.23.8.21",
                label="Касса",
                original_host="172.23.8.21",
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
    monkeypatch.setattr(settings, "HONEST_SIGN_TARGETS", "172.23.8.21|Касса")

    async def fake_initialize(target):
        return HonestSignInitializePublic(
            host=target.host,
            label=target.label,
            original_host=target.original_host,
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


def test_honest_sign_ip_update_requires_superuser(client, user_token: str, monkeypatch):
    monkeypatch.setattr(settings, "HONEST_SIGN_TARGETS", "172.23.8.21|Касса")

    response = client.patch(
        "/api/v1/honest-sign/172.23.8.21/ip",
        json={"new_ip": "172.23.8.6"},
        headers={"Authorization": f"Bearer {user_token}"},
    )

    assert response.status_code == 403


def test_honest_sign_ip_update_redirects_target(client, admin_token: str, monkeypatch):
    monkeypatch.setattr(settings, "HONEST_SIGN_TARGETS", "172.23.8.21|Касса")

    response = client.patch(
        "/api/v1/honest-sign/172.23.8.21/ip",
        json={"new_ip": "172.23.8.6"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json()["host"] == "172.23.8.6"
    assert response.json()["original_host"] == "172.23.8.21"

    listed = client.get(
        "/api/v1/honest-sign/targets",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert listed.json()["data"][0]["host"] == "172.23.8.6"


def test_honest_sign_stored_statuses_come_from_the_background_check(client, user_token: str, db_session, monkeypatch):
    monkeypatch.setattr(settings, "HONEST_SIGN_TARGETS", "172.23.8.21|Касса")
    row = HonestSignStatusPublic(
        host="172.23.8.21",
        label="Касса",
        original_host="172.23.8.21",
        reachable=True,
        status="ready",
        version="2.5.1",
        ready=True,
        checked_at=datetime.now(UTC).isoformat(),
    )
    record_check_results(db_session, [row])

    response = client.get("/api/v1/honest-sign/statuses", headers={"Authorization": f"Bearer {user_token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["data"][0]["ready"] is True
    assert body["data"][0]["state_since"] is not None


def test_honest_sign_targets_report_auto_check_settings(client, user_token: str, monkeypatch):
    monkeypatch.setattr(settings, "HONEST_SIGN_TARGETS", "172.23.8.21|Касса")
    monkeypatch.setattr(settings, "HONEST_SIGN_AUTO_CHECK_ENABLED", True)
    monkeypatch.setattr(settings, "HONEST_SIGN_AUTO_CHECK_INTERVAL_MINUTES", 10)

    body = client.get("/api/v1/honest-sign/targets", headers={"Authorization": f"Bearer {user_token}"}).json()

    assert body["auto_check_enabled"] is True
    assert body["auto_check_interval_minutes"] == 10


def test_honest_sign_cash_register_links_join_targets_status_and_registers(
    client, user_token: str, db_session, monkeypatch
):
    monkeypatch.setattr(settings, "HONEST_SIGN_TARGETS", "172.23.8.21|A15|VNK-KKM-1501,172.23.8.22|A15")
    monkeypatch.setattr(settings, "HONEST_SIGN_API_LOGIN", "user")
    monkeypatch.setattr(settings, "HONEST_SIGN_API_PASSWORD", "password")
    cash = CashRegister(kkm_number="1501", hostname="vnk-kkm-1501")
    db_session.add(cash)
    db_session.commit()
    db_session.refresh(cash)
    record_check_results(
        db_session,
        [
            HonestSignStatusPublic(
                host="172.23.8.21",
                label="A15",
                hostname="VNK-KKM-1501",
                original_host="172.23.8.21",
                reachable=True,
                status="not_initialized",
                ready=False,
                checked_at=datetime.now(UTC).isoformat(),
            )
        ],
    )

    response = client.get("/api/v1/honest-sign/cash-registers", headers={"Authorization": f"Bearer {user_token}"})

    assert response.status_code == 200
    body = response.json()
    assert [(row["cash_register_id"], row["target"]["host"]) for row in body["data"]] == [(str(cash.id), "172.23.8.21")]
    assert body["data"][0]["status"]["status"] == "not_initialized"
    assert [t["host"] for t in body["unmatched_targets"]] == ["172.23.8.22"]
    assert body["ambiguous_hostnames"] == []
    assert body["status_configured"] is True
