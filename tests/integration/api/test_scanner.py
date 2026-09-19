from fastapi.testclient import TestClient

from app.api.routes import scanner as scanner_routes
from app.domains.inventory.models import MediaPlayer, Printer
from app.services.mac_rediscovery import MacRediscoveryMatch, MacRediscoveryTarget


def test_get_scanner_settings_requires_auth(client: TestClient):
    response = client.get("/api/v1/scanner/settings")
    assert response.status_code in (401, 403)


def test_get_scanner_settings(client: TestClient, admin_token: str):
    response = client.get(
        "/api/v1/scanner/settings",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert "subnet" in response.json()
    assert "ports" in response.json()


def test_scanner_status_reads_progress_from_redis(client: TestClient, admin_token: str):
    import asyncio
    import json

    from app.core.redis import get_redis
    from app.services.scanner import SCAN_KEY_PROGRESS

    async def _seed():
        r = await get_redis()
        await r.set(SCAN_KEY_PROGRESS, json.dumps({"status": "running", "scanned": 1, "total": 10, "found": 0, "message": None}))

    asyncio.run(_seed())
    response = client.get(
        "/api/v1/scanner/status",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert response.json()["total"] == 10


def test_rediscover_by_mac_updates_known_devices(client: TestClient, admin_token: str, db_session, monkeypatch):
    printer = Printer(
        store_name="Store 1",
        model="HP",
        ip_address="10.10.98.10",
        mac_address="aa:bb:cc:dd:ee:01",
    )
    player = MediaPlayer(
        device_type="nettop",
        name="Player 1",
        model="Nettop",
        ip_address="10.10.98.20",
        mac_address="AA-BB-CC-DD-EE-02",
    )
    db_session.add(printer)
    db_session.add(player)
    db_session.commit()
    db_session.refresh(printer)
    db_session.refresh(player)

    async def _fake_resolve(targets: list[MacRediscoveryTarget], subnets: list[str] | None = None, session=None):
        assert subnets == ["10.10.98.0/24"]
        by_kind = {target.device_kind: target for target in targets}
        return [
            MacRediscoveryMatch(by_kind["printer"], "aa:bb:cc:dd:ee:01", "10.10.98.11"),
            MacRediscoveryMatch(by_kind["media_player"], "aa:bb:cc:dd:ee:02", "10.10.98.21"),
        ]

    monkeypatch.setattr(scanner_routes, "resolve_devices_by_mac", _fake_resolve)
    response = client.post(
        "/api/v1/scanner/rediscover-by-mac",
        json={"subnets": ["10.10.98.0/24"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["updated"] == 2
    assert {item["status"] for item in payload["data"]} == {"updated"}
    db_session.refresh(printer)
    db_session.refresh(player)
    assert printer.ip_address == "10.10.98.11"
    assert player.ip_address == "10.10.98.21"


def test_rediscover_by_mac_reports_conflict(client: TestClient, admin_token: str, db_session, monkeypatch):
    source = Printer(
        store_name="Source",
        model="HP",
        ip_address="10.10.98.10",
        mac_address="aa:bb:cc:dd:ee:01",
    )
    taken = Printer(store_name="Taken", model="HP", ip_address="10.10.98.11")
    db_session.add(source)
    db_session.add(taken)
    db_session.commit()
    db_session.refresh(source)

    async def _fake_resolve(targets: list[MacRediscoveryTarget], subnets: list[str] | None = None, session=None):
        return [MacRediscoveryMatch(targets[0], "aa:bb:cc:dd:ee:01", "10.10.98.11")]

    monkeypatch.setattr(scanner_routes, "resolve_devices_by_mac", _fake_resolve)
    response = client.post(
        "/api/v1/scanner/rediscover-by-mac",
        json={"device_kinds": ["printer"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    assert response.json()["updated"] == 0
    assert response.json()["data"][0]["status"] == "conflict"
    db_session.refresh(source)
    assert source.ip_address == "10.10.98.10"


def test_rediscover_by_mac_dry_run_does_not_update(client: TestClient, admin_token: str, db_session, monkeypatch):
    printer = Printer(
        store_name="Dry run",
        model="HP",
        ip_address="10.10.98.30",
        mac_address="aa:bb:cc:dd:ee:03",
    )
    db_session.add(printer)
    db_session.commit()
    db_session.refresh(printer)

    async def _fake_resolve(targets: list[MacRediscoveryTarget], subnets: list[str] | None = None, session=None):
        return [MacRediscoveryMatch(targets[0], "aa:bb:cc:dd:ee:03", "10.10.98.31")]

    monkeypatch.setattr(scanner_routes, "resolve_devices_by_mac", _fake_resolve)
    response = client.post(
        "/api/v1/scanner/rediscover-by-mac",
        json={"device_kinds": ["printer"], "apply": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    assert response.json()["updated"] == 0
    assert response.json()["data"][0]["status"] == "found"
    db_session.refresh(printer)
    assert printer.ip_address == "10.10.98.30"
