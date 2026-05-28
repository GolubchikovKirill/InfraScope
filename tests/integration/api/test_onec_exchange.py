from app.api.routes import onec_exchange as onec_routes


def test_onec_exchange_requires_auth(client):
    response = client.post("/api/v1/1c-exchange/by-barcode", json={"barcode": "4601234567890"})
    assert response.status_code == 401


def test_onec_exchange_requires_superuser(client, user_token: str):
    response = client.post(
        "/api/v1/1c-exchange/by-barcode",
        json={"barcode": "4601234567890"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 403


def test_onec_exchange_success(client, admin_token: str, monkeypatch):
    captured: dict = {}

    async def _fake_exchange(**_kwargs):
        captured.update(_kwargs)
        return {
            "target": _kwargs.get("target"),
            "ok": True,
            "message": "ok",
            "status_code": 200,
            "request_id": "req-1",
            "payload": {"accepted": True},
        }

    monkeypatch.setattr(onec_routes.onec_exchange_service, "exchange_product_docs_by_barcode", _fake_exchange)

    response = client.post(
        "/api/v1/1c-exchange/by-barcode",
        json={
            "target": "duty_paid",
            "barcode": "4601234567890",
            "cash_register_hostnames": ["A001-KKM-01", "A001-KKM-02"],
            "source": "test",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["target"] == "duty_paid"
    assert body["request_id"] == "req-1"
    assert body["error_kind"] is None
    assert captured["target"] == "duty_paid"


def test_onec_exchange_propagates_error_kind(client, admin_token: str, monkeypatch):
    async def _fake_exchange(**_kwargs):
        return type(
            "OneCResult",
            (),
            {
                "to_dict": lambda self: {
                    "target": "duty_free",
                    "ok": False,
                    "message": "1C timeout",
                    "status_code": None,
                    "request_id": None,
                    "payload": None,
                    "error_kind": "timeout",
                }
            },
        )()

    monkeypatch.setattr(onec_routes.onec_exchange_service, "exchange_product_docs_by_barcode", _fake_exchange)

    response = client.post(
        "/api/v1/1c-exchange/by-barcode",
        json={"barcode": "4601234567890"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json()["error_kind"] == "timeout"
