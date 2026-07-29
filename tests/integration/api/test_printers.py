from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.api.routes import printers as printer_routes
from app.domains.operations.models import EventLog


def test_create_printer_and_reject_duplicate_ip(client: TestClient, admin_token: str, monkeypatch):
    async def _no_mac(*args, **kwargs):
        return None

    monkeypatch.setattr(printer_routes, "resolve_mac_for_ip_address", _no_mac)
    payload = {
        "printer_type": "laser",
        "connection_type": "ip",
        "store_name": "Store A",
        "model": "HP M404",
        "ip_address": "10.10.10.10",
        "snmp_community": "public",
    }
    first = client.post(
        "/api/v1/printers/",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert first.status_code == 200

    second = client.post(
        "/api/v1/printers/",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert second.status_code == 400


def test_create_printer_autofills_mac_from_ip(client: TestClient, admin_token: str, monkeypatch):
    async def _fake_resolve_mac(ip_address: str, **kwargs):
        assert ip_address == "10.10.10.11"
        return "aa:bb:cc:dd:ee:11"

    monkeypatch.setattr(printer_routes, "resolve_mac_for_ip_address", _fake_resolve_mac)
    response = client.post(
        "/api/v1/printers/",
        json={
            "printer_type": "laser",
            "connection_type": "ip",
            "store_name": "Store B",
            "model": "HP M404",
            "ip_address": "10.10.10.11",
            "snmp_community": "public",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    assert response.json()["mac_address"] == "aa:bb:cc:dd:ee:11"
    assert response.json()["mac_status"] == "verified"


def test_poll_usb_printer_is_blocked(client: TestClient, admin_token: str):
    create = client.post(
        "/api/v1/printers/",
        json={
            "printer_type": "label",
            "connection_type": "usb",
            "store_name": "Store USB",
            "model": "Zebra",
            "host_pc": "POS-01",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create.status_code == 200
    printer_id = create.json()["id"]

    poll = client.post(
        f"/api/v1/printers/{printer_id}/poll",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert poll.status_code == 400


def test_poll_all_printers_uses_polling_service_when_enabled(client: TestClient, admin_token: str, monkeypatch):
    async def _fake_proxy_request(**kwargs):
        assert kwargs["path"] == "/poll/printers"
        return {"data": [], "count": 0}

    monkeypatch.setattr(printer_routes.settings, "POLLING_SERVICE_ENABLED", True)
    monkeypatch.setattr(printer_routes, "_proxy_request", _fake_proxy_request)
    response = client.post(
        "/api/v1/printers/poll-all",
        params={"printer_type": "laser"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json()["count"] == 0


def test_read_printers_reports_offline_count_24h(client: TestClient, admin_token: str, db_session, monkeypatch):
    async def _no_mac(*args, **kwargs):
        return None

    monkeypatch.setattr(printer_routes, "resolve_mac_for_ip_address", _no_mac)
    create = client.post(
        "/api/v1/printers/",
        json={
            "printer_type": "laser",
            "connection_type": "ip",
            "store_name": "Store Flapping",
            "model": "HP M404",
            "ip_address": "10.10.10.60",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create.status_code == 200

    now = datetime.now(UTC)
    for _ in range(3):
        db_session.add(
            EventLog(
                category="device",
                event_type="device_offline",
                severity="warning",
                device_kind="printer",
                device_name="Store Flapping",
                message="Printer 'Store Flapping' is now offline",
                created_at=now,
            )
        )
    db_session.commit()

    response = client.get(
        "/api/v1/printers/",
        params={"store_name": "Store Flapping"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    rows = response.json()["data"]
    assert len(rows) == 1
    assert rows[0]["offline_count_24h"] == 3


def test_cartridge_stock_sync_adjust_issue_and_history(client: TestClient, admin_token: str, monkeypatch):
    async def _no_mac(*args, **kwargs):
        return None

    monkeypatch.setattr(printer_routes, "resolve_mac_for_ip_address", _no_mac)
    create = client.post(
        "/api/v1/printers/",
        json={
            "printer_type": "laser",
            "connection_type": "ip",
            "store_name": "Store Toner",
            "model": "HP M404",
            "ip_address": "10.10.10.40",
            "toner_black_name": "CF259A",
            "toner_cyan_name": "W2031A",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create.status_code == 200

    synced = client.post(
        "/api/v1/printers/cartridges/sync",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert synced.status_code == 200
    rows = synced.json()["data"]
    assert {row["cartridge_name"] for row in rows} == {"CF259A", "W2031A"}

    stock = next(row for row in rows if row["cartridge_name"] == "CF259A")
    adjusted = client.patch(
        f"/api/v1/printers/cartridges/{stock['id']}",
        json={"quantity_on_hand": 3, "minimum_stock": 1, "note": "initial count"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert adjusted.status_code == 200
    assert adjusted.json()["quantity_on_hand"] == 3

    issued = client.post(
        f"/api/v1/printers/cartridges/{stock['id']}/issue",
        json={"quantity": 1, "note": "issued to Store Toner"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert issued.status_code == 200
    assert issued.json()["quantity_on_hand"] == 2

    history = client.get(
        f"/api/v1/printers/cartridges/{stock['id']}/movements",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert history.status_code == 200
    assert [row["delta"] for row in history.json()["data"]] == [-1, 3]


def test_cartridge_issue_rejects_when_stock_is_empty(client: TestClient, admin_token: str, monkeypatch):
    async def _no_mac(*args, **kwargs):
        return None

    monkeypatch.setattr(printer_routes, "resolve_mac_for_ip_address", _no_mac)
    client.post(
        "/api/v1/printers/",
        json={
            "printer_type": "laser",
            "connection_type": "ip",
            "store_name": "Store Empty",
            "model": "HP M404",
            "ip_address": "10.10.10.41",
            "toner_black_name": "CF259A",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    synced = client.post(
        "/api/v1/printers/cartridges/sync",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    stock = synced.json()["data"][0]

    issued = client.post(
        f"/api/v1/printers/cartridges/{stock['id']}/issue",
        json={"quantity": 1},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert issued.status_code == 409
