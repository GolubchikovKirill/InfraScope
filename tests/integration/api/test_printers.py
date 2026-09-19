from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.api.routes import printers as printer_routes
from app.domains.inventory.schemas import PrintersPublic
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


def test_poll_all_printers_polls_in_process_for_the_requested_type(client: TestClient, admin_token: str, monkeypatch):
    seen: list[str] = []

    async def _fake_poll_all(*, session, printer_type):
        seen.append(printer_type)
        return PrintersPublic(data=[], count=0)

    monkeypatch.setattr(printer_routes, "poll_all_printers_local", _fake_poll_all)
    response = client.post(
        "/api/v1/printers/poll-all",
        params={"printer_type": "label"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json()["count"] == 0
    assert seen == ["label"]


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


def test_cartridge_card_full_crud(client: TestClient, admin_token: str):
    headers = {"Authorization": f"Bearer {admin_token}"}

    created = client.post(
        "/api/v1/printers/cartridges",
        json={
            "cartridge_name": "  Hi-Black  ·  BCR-CC530A [K]  ",
            "toner_color": "BLACK",
            "compatible_printer_models": "HP Color LaserJet CM2320,  CP2025",
            "quantity_on_hand": 2,
            "minimum_stock": 1,
            "note": "заведено вручную",
        },
        headers=headers,
    )
    assert created.status_code == 200
    body = created.json()
    # Whitespace runs collapse so visually identical names cannot split in two.
    assert body["cartridge_name"] == "Hi-Black · BCR-CC530A [K]"
    assert body["toner_color"] == "black"
    assert body["compatible_printer_models"] == "HP Color LaserJet CM2320, CP2025"
    assert body["quantity_on_hand"] == 2
    stock_id = body["id"]

    opening = client.get(f"/api/v1/printers/cartridges/{stock_id}/movements", headers=headers)
    assert [row["delta"] for row in opening.json()["data"]] == [2]

    renamed = client.patch(
        f"/api/v1/printers/cartridges/{stock_id}",
        json={
            "cartridge_name": "Hi-Black · BCR-CC530A",
            "compatible_printer_models": "HP CM2320",
            "toner_color": None,
        },
        headers=headers,
    )
    assert renamed.status_code == 200
    assert renamed.json()["cartridge_name"] == "Hi-Black · BCR-CC530A"
    assert renamed.json()["compatible_printer_models"] == "HP CM2320"
    assert renamed.json()["toner_color"] is None

    duplicate = client.post(
        "/api/v1/printers/cartridges",
        json={"cartridge_name": "Hi-Black · BCR-CC530A"},
        headers=headers,
    )
    assert duplicate.status_code == 409

    archived = client.delete(f"/api/v1/printers/cartridges/{stock_id}", headers=headers)
    assert archived.status_code == 200
    assert archived.json()["is_active"] is False
    # Archiving must not throw the counted stock away.
    assert archived.json()["quantity_on_hand"] == 2

    assert stock_id not in [row["id"] for row in client.get("/api/v1/printers/cartridges", headers=headers).json()["data"]]
    with_archive = client.get("/api/v1/printers/cartridges?include_inactive=true", headers=headers)
    assert stock_id in [row["id"] for row in with_archive.json()["data"]]

    restored = client.patch(
        f"/api/v1/printers/cartridges/{stock_id}",
        json={"is_active": True},
        headers=headers,
    )
    assert restored.status_code == 200
    assert restored.json()["is_active"] is True


def test_cartridge_rename_onto_existing_name_is_rejected(client: TestClient, admin_token: str):
    headers = {"Authorization": f"Bearer {admin_token}"}
    first = client.post(
        "/api/v1/printers/cartridges", json={"cartridge_name": "W2070A"}, headers=headers
    )
    second = client.post(
        "/api/v1/printers/cartridges", json={"cartridge_name": "W2071A"}, headers=headers
    )
    assert first.status_code == 200 and second.status_code == 200

    clash = client.patch(
        f"/api/v1/printers/cartridges/{second.json()['id']}",
        json={"cartridge_name": "W2070A"},
        headers=headers,
    )
    assert clash.status_code == 409

    # Renaming a row to the name it already holds must stay a no-op, not a clash.
    same = client.patch(
        f"/api/v1/printers/cartridges/{second.json()['id']}",
        json={"cartridge_name": "W2071A", "minimum_stock": 2},
        headers=headers,
    )
    assert same.status_code == 200
    assert same.json()["minimum_stock"] == 2


def test_cartridge_card_rejects_bad_color_and_non_superuser(client: TestClient, admin_token: str, user_token: str):
    bad_color = client.post(
        "/api/v1/printers/cartridges",
        json={"cartridge_name": "TK-5240K", "toner_color": "оранжевый"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert bad_color.status_code == 422

    forbidden = client.post(
        "/api/v1/printers/cartridges",
        json={"cartridge_name": "TK-5240C"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert forbidden.status_code == 403
