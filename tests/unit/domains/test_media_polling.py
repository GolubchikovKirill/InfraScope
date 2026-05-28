from __future__ import annotations

from app.domains.inventory.media_polling import (
    LightMediaPollResult,
    apply_media_poll_result,
    poll_media_player_batch,
    poll_one_media_player,
)
from app.domains.inventory.models import MediaPlayer


def test_apply_media_poll_result_updates_online_metadata() -> None:
    player = MediaPlayer(
        device_type="nettop",
        name="Music PC",
        model="Nettop",
        ip_address="10.10.10.20",
    )
    result = LightMediaPollResult(
        is_online=True,
        hostname="NETTOP-01",
        os_info="Windows 10",
        uptime="1d",
        open_ports=[445, 3389],
        mac_address="aa:bb:cc:dd:ee:ff",
    )

    apply_media_poll_result(player, result)

    assert player.is_online is True
    assert player.hostname == "NETTOP-01"
    assert player.open_ports == "445,3389"
    assert player.mac_address == "aa:bb:cc:dd:ee:ff"


def test_apply_media_poll_result_marks_offline_without_erasing_metadata() -> None:
    player = MediaPlayer(
        device_type="nettop",
        name="Music PC",
        model="Nettop",
        ip_address="10.10.10.20",
        hostname="NETTOP-01",
    )

    apply_media_poll_result(player, None)

    assert player.is_online is False
    assert player.hostname == "NETTOP-01"


def test_poll_one_iconbit_uses_8081_healthcheck(monkeypatch) -> None:
    player = MediaPlayer(
        device_type="iconbit",
        name="Iconbit",
        model="Iconbit",
        ip_address="10.10.10.88",
    )

    monkeypatch.setattr("app.domains.inventory.media_polling.poll_jitter_sync", lambda: None)
    monkeypatch.setattr("app.domains.inventory.media_polling.check_port", lambda _ip, port, timeout: port == 8081)

    def should_not_call_generic_poll(_address: str):
        raise AssertionError("generic poll should not be used for iconbit")

    monkeypatch.setattr("app.domains.inventory.media_polling.poll_device_sync", should_not_call_generic_poll)

    ip, result = poll_one_media_player(player)

    assert ip == "10.10.10.88"
    assert isinstance(result, LightMediaPollResult)
    assert result.is_online is True
    assert result.open_ports == [8081]


def test_poll_media_player_batch_preserves_each_ip(monkeypatch) -> None:
    players = [
        MediaPlayer(device_type="nettop", name="A", model="Nettop", ip_address="10.10.10.20"),
        MediaPlayer(device_type="nettop", name="B", model="Nettop", ip_address="10.10.10.21"),
    ]

    def fake_poll_one(player: MediaPlayer):
        return player.ip_address, LightMediaPollResult(is_online=player.ip_address.endswith(".20"))

    monkeypatch.setattr("app.domains.inventory.media_polling.poll_one_media_player", fake_poll_one)

    result = poll_media_player_batch(players)

    assert result["10.10.10.20"].is_online is True
    assert result["10.10.10.21"].is_online is False
