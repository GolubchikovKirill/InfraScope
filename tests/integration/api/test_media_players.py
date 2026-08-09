from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.api.routes import media_players as media_routes
from app.domains.inventory import media_polling


@dataclass
class _PollResult:
    is_online: bool = True
    hostname: str | None = "NETTOP-01"
    os_info: str | None = "Windows 10"
    uptime: str | None = "1д 2ч"
    open_ports: list[int] | None = None
    mac_address: str | None = "aa:bb:cc:dd:ee:ff"


def test_create_media_player_and_poll(client: TestClient, admin_token: str, monkeypatch):
    async def _no_move(_targets):
        return []

    async def _no_mac(*args, **kwargs):
        return None

    async def _poll_one(_player, *, port_scan_semaphore):
        return "10.10.10.20", _PollResult(open_ports=[445, 3389])

    monkeypatch.setattr(media_polling, "poll_one_media_player_async", _poll_one)
    monkeypatch.setattr(media_polling, "resolve_devices_by_mac", _no_move)
    monkeypatch.setattr(media_routes, "resolve_mac_for_ip_address", _no_mac)

    created = client.post(
        "/api/v1/media-players/",
        json={
            "device_type": "nettop",
            "name": "Music PC",
            "model": "Nettop",
            "ip_address": "10.10.10.20",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 200
    player_id = created.json()["id"]

    polled = client.post(
        f"/api/v1/media-players/{player_id}/poll",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert polled.status_code == 200
    assert polled.json()["is_online"] is True


def test_iconbit_discovery_scan_and_results(client: TestClient, admin_token: str, monkeypatch):
    async def _fake_run(kind: str, subnet: str, ports: str, known_devices: list[dict]):
        assert kind == "iconbit"
        assert subnet == "10.10.98.0/24"
        assert ports == "8081,80,443"
        assert isinstance(known_devices, list)
        return None

    async def _fake_progress(_kind: str):
        return {"status": "done", "scanned": 254, "total": 254, "found": 1, "message": None}

    async def _fake_results(_kind: str):
        return [
            {
                "ip": "10.10.98.120",
                "mac": "aa:bb:cc:11:22:33",
                "open_ports": [8081],
                "hostname": "ICONBIT-01",
                "model_info": "Iconbit",
                "vendor": "generic",
                "device_kind": "iconbit",
                "is_known": False,
                "known_device_id": None,
                "ip_changed": False,
                "old_ip": None,
            }
        ]

    monkeypatch.setattr(media_routes, "run_discovery_scan", _fake_run)
    monkeypatch.setattr(media_routes, "get_discovery_progress", _fake_progress)
    monkeypatch.setattr(media_routes, "get_discovery_results", _fake_results)

    scan_resp = client.post(
        "/api/v1/media-players/discover/scan",
        json={"subnet": "10.10.98.0/24", "ports": "8081,80,443"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert scan_resp.status_code == 200
    assert scan_resp.json()["status"] == "running"

    results_resp = client.get(
        "/api/v1/media-players/discover/results",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert results_resp.status_code == 200
    assert results_resp.json()["progress"]["status"] == "done"
    assert results_resp.json()["devices"][0]["device_kind"] == "iconbit"


def test_iconbit_discovery_add_and_update_ip(client: TestClient, admin_token: str, monkeypatch):
    async def _auto_mac(ip_address: str, **kwargs):
        return "aa:bb:cc:dd:ee:13" if ip_address == "10.10.98.123" else None

    monkeypatch.setattr(media_routes, "resolve_mac_for_ip_address", _auto_mac)
    create_resp = client.post(
        "/api/v1/media-players/discover/add",
        json={
            "ip_address": "10.10.98.121",
            "name": "Iconbit New",
            "model": "Iconbit",
            "mac_address": "aa:bb:cc:dd:ee:11",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_resp.status_code == 200
    player_id = create_resp.json()["id"]
    assert create_resp.json()["device_type"] == "iconbit"

    update_resp = client.post(
        f"/api/v1/media-players/discover/update-ip/{player_id}",
        params={"new_ip": "10.10.98.122", "new_mac": "aa:bb:cc:dd:ee:12"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["ip_address"] == "10.10.98.122"
    assert update_resp.json()["mac_address"] == "aa:bb:cc:dd:ee:12"

    create_auto = client.post(
        "/api/v1/media-players/discover/add",
        json={
            "ip_address": "10.10.98.123",
            "name": "Iconbit Auto MAC",
            "model": "Iconbit",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_auto.status_code == 200
    assert create_auto.json()["mac_address"] == "aa:bb:cc:dd:ee:13"


def test_poll_all_iconbit_uses_8081_healthcheck(client: TestClient, admin_token: str, monkeypatch):
    async def _no_mac(*args, **kwargs):
        return None

    class _FakeRedis:
        async def set(self, *_args, **_kwargs):
            return True

        async def delete(self, *_args, **_kwargs):
            return 1

    async def _redis():
        return _FakeRedis()

    monkeypatch.setattr(media_routes, "resolve_mac_for_ip_address", _no_mac)
    monkeypatch.setattr(media_polling, "get_redis", _redis)
    created = client.post(
        "/api/v1/media-players/",
        json={
            "device_type": "iconbit",
            "name": "Iconbit Room",
            "model": "Iconbit",
            "ip_address": "10.10.10.88",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 200

    monkeypatch.setattr(media_polling, "check_port", lambda _ip, port=8081, timeout=2.5: port == 8081)

    async def _should_not_be_called(_address: str, **_kwargs):
        raise RuntimeError("generic poll should not be used for iconbit in bulk")

    monkeypatch.setattr(media_polling, "poll_device", _should_not_be_called)

    polled = client.post(
        "/api/v1/media-players/poll-all",
        params={"device_type": "iconbit"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert polled.status_code == 200
    assert polled.json()["count"] == 1
    assert polled.json()["data"][0]["is_online"] is True


def test_iconbit_bulk_play_uses_network_control_service_when_enabled(client: TestClient, admin_token: str, monkeypatch):
    async def _fake_proxy_request(**kwargs):
        assert kwargs["path"] == "/iconbit/bulk-play"
        return {"success": 2, "failed": 0}

    monkeypatch.setattr(media_routes.settings, "NETWORK_CONTROL_SERVICE_ENABLED", True)
    monkeypatch.setattr(media_routes, "_proxy_request", _fake_proxy_request)

    response = client.post(
        "/api/v1/media-players/iconbit/bulk-play",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json()["success"] == 2
