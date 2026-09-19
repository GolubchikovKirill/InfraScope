from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.api.routes import media_players as media_routes
from app.domains.inventory import media_polling
from app.domains.inventory.models import MediaPlayer
from app.domains.inventory.reachability import ReachabilityResult


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

    monkeypatch.setattr(
        media_polling,
        "probe_tcp_endpoint",
        lambda _ip, *, port, timeout, probe_scope: ReachabilityResult(is_online=port == 8081),
    )

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


def test_iconbit_bulk_play_runs_in_process_against_every_iconbit(client: TestClient, admin_token: str, db_session, monkeypatch):
    for n in (1, 2):
        db_session.add(MediaPlayer(device_type="iconbit", name=f"Iconbit {n}", model="Iconbit", ip_address=f"10.10.98.{30 + n}"))
    db_session.add(MediaPlayer(device_type="nettop", name="Not an iconbit", model="Nettop", ip_address="10.10.98.99"))
    db_session.commit()

    played: list[str] = []

    def _fake_play(ip: str) -> bool:
        played.append(ip)
        return ip != "10.10.98.32"

    monkeypatch.setattr(media_routes, "iconbit_play", _fake_play)

    response = client.post(
        "/api/v1/media-players/iconbit/bulk-play",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json() == {"success": 1, "failed": 1}
    assert sorted(played) == ["10.10.98.31", "10.10.98.32"]
