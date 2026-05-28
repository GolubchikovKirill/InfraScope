from app.api.routes import qr_generator as qr_routes


def test_qr_generator_requires_auth(client):
    response = client.post("/api/v1/qr-generator/export", json={})
    assert response.status_code == 401


def test_qr_generator_requires_superuser(client, user_token: str):
    response = client.post(
        "/api/v1/qr-generator/export",
        json={
            "db_mode": "duty_free",
            "airport_code": "4007",
        },
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 403


def test_qr_generator_returns_zip(client, admin_token: str, monkeypatch):
    captured = {}

    def _fake_generate(_params):
        captured["params"] = _params
        return b"fake-zip-content"

    monkeypatch.setattr(qr_routes.qr_export_service, "generate_zip", _fake_generate)

    response = client.post(
        "/api/v1/qr-generator/export",
        json={
            "db_mode": "both",
            "airport_code": "4007",
            "surnames": "Иванов",
            "add_login": True,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")
    assert response.content == b"fake-zip-content"
    assert captured["params"].both_databases is True


def test_qr_generator_uses_channel_specific_database_for_duty_paid(client, admin_token: str, monkeypatch):
    captured = {}

    monkeypatch.setattr(qr_routes.settings, "QR_SQL_DUTY_PAID_SERVER", "paid-sql")
    monkeypatch.setattr(qr_routes.settings, "QR_SQL_DUTY_PAID_DATABASE", "PaidCash")

    def _fake_generate(_params):
        captured["params"] = _params
        return b"fake-zip-content"

    monkeypatch.setattr(qr_routes.qr_export_service, "generate_zip", _fake_generate)

    response = client.post(
        "/api/v1/qr-generator/export",
        json={
            "db_mode": "duty_paid",
            "airport_code": "4007",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    assert captured["params"].server == "paid-sql"
    assert captured["params"].database == "PaidCash"
    assert captured["params"].both_databases is False


def test_qr_generator_returns_504_on_sql_timeout(client, admin_token: str, monkeypatch):
    import time

    original_timeout = qr_routes.settings.QR_SQL_TIMEOUT_SECONDS
    monkeypatch.setattr(qr_routes.settings, "QR_SQL_TIMEOUT_SECONDS", 0.01)

    def _slow_generate(_params):
        time.sleep(0.1)
        return b"never-used"

    monkeypatch.setattr(qr_routes.qr_export_service, "generate_zip", _slow_generate)

    response = client.post(
        "/api/v1/qr-generator/export",
        json={
            "db_mode": "duty_free",
            "airport_code": "4007",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    monkeypatch.setattr(qr_routes.settings, "QR_SQL_TIMEOUT_SECONDS", original_timeout)

    assert response.status_code == 504
    assert "таймаут SQL" in response.json()["detail"]
