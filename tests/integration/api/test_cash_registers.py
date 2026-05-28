from app.api.routes import cash_registers as cash_routes
from app.domains.operations import cash_register_polling


class _BusyRedis:
    async def set(self, *_args, **_kwargs):
        return False

    async def delete(self, *_args, **_kwargs):
        return 0


def test_create_cash_register(client, admin_token: str):
    payload = {
        "kkm_number": "001",
        "store_code": "A1",
        "kkm_type": "retail",
        "hostname": "cash-a1",
    }
    response = client.post(
        "/api/v1/cash-registers/",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json()["kkm_number"] == "001"


def test_poll_all_cash_registers_uses_polling_service_when_enabled(client, admin_token: str, monkeypatch):
    async def _fake_proxy_request(**kwargs):
        assert kwargs["path"] == "/poll/cash-registers"
        return {"data": [], "count": 0}

    monkeypatch.setattr(cash_routes.settings, "POLLING_SERVICE_ENABLED", True)
    monkeypatch.setattr(cash_routes, "_proxy_request", _fake_proxy_request)

    response = client.post(
        "/api/v1/cash-registers/poll-all",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json()["count"] == 0


def test_poll_cash_register_updates_reachability(client, admin_token: str, monkeypatch):
    monkeypatch.setattr(cash_register_polling, "probe_cash_register", lambda _hostname: (False, "port_closed"))

    created = client.post(
        "/api/v1/cash-registers/",
        json={"kkm_number": "002", "kkm_type": "retail", "hostname": "cash-a2"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 200
    cash_id = created.json()["id"]

    response = client.post(
        f"/api/v1/cash-registers/{cash_id}/poll",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    assert response.json()["is_online"] is False
    assert response.json()["reachability_reason"] == "port_closed"


def test_poll_all_cash_registers_skips_duplicate_network_scan(client, admin_token: str, monkeypatch):
    async def _busy_redis():
        return _BusyRedis()

    monkeypatch.setattr(cash_register_polling, "get_redis", _busy_redis)
    monkeypatch.setattr(
        cash_register_polling,
        "_probe_cash_registers_bulk",
        lambda _rows: (_ for _ in ()).throw(AssertionError("duplicate poll should not probe network")),
    )

    created = client.post(
        "/api/v1/cash-registers/",
        json={"kkm_number": "003", "kkm_type": "retail", "hostname": "cash-busy"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 200

    response = client.post(
        "/api/v1/cash-registers/poll-all",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["data"][0]["hostname"] == "cash-busy"
