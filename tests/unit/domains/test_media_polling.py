from __future__ import annotations

import asyncio

from app.domains.inventory import media_polling
from app.domains.inventory.media_polling import (
    LightMediaPollResult,
    apply_media_poll_result,
    poll_media_player_batch,
    poll_one_media_player_async,
)
from app.domains.inventory.models import MediaPlayer
from app.domains.inventory.reachability import ReachabilityResult
from app.services.mac_rediscovery import MacRediscoveryMatch


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

    async def _no_jitter():
        return None

    async def _probe(_ip, *, port, timeout, probe_scope):
        return ReachabilityResult(is_online=port == 8081)

    monkeypatch.setattr("app.domains.inventory.media_polling.poll_jitter_async", _no_jitter)
    monkeypatch.setattr("app.domains.inventory.media_polling.probe_tcp_endpoint_async", _probe)

    async def should_not_call_generic_poll(_address: str, **_kwargs):
        raise AssertionError("generic poll should not be used for iconbit")

    monkeypatch.setattr("app.domains.inventory.media_polling.poll_device", should_not_call_generic_poll)

    ip, result = asyncio.run(poll_one_media_player_async(player, port_scan_semaphore=asyncio.Semaphore(1)))

    assert ip == "10.10.10.88"
    assert isinstance(result, LightMediaPollResult)
    assert result.is_online is True
    assert result.open_ports == [8081]


def test_poll_media_player_batch_preserves_each_ip(monkeypatch) -> None:
    players = [
        MediaPlayer(device_type="nettop", name="A", model="Nettop", ip_address="10.10.10.20"),
        MediaPlayer(device_type="nettop", name="B", model="Nettop", ip_address="10.10.10.21"),
    ]

    async def fake_poll_one(player: MediaPlayer, *, port_scan_semaphore):
        return player.ip_address, LightMediaPollResult(is_online=player.ip_address.endswith(".20"))

    monkeypatch.setattr("app.domains.inventory.media_polling.poll_one_media_player_async", fake_poll_one)

    result = asyncio.run(poll_media_player_batch(players))

    online_20 = result["10.10.10.20"]
    offline_21 = result["10.10.10.21"]
    assert online_20 is not None and online_20.is_online is True
    assert offline_21 is not None and offline_21.is_online is False


def test_poll_media_player_batch_shares_one_port_semaphore(monkeypatch) -> None:
    players = [
        MediaPlayer(device_type="nettop", name=f"A{i}", model="Nettop", ip_address=f"10.10.10.{i}")
        for i in range(20, 24)
    ]
    seen_semaphores = []

    async def fake_poll_one(player: MediaPlayer, *, port_scan_semaphore):
        seen_semaphores.append(port_scan_semaphore)
        await asyncio.sleep(0)
        return player.ip_address, LightMediaPollResult(is_online=True)

    monkeypatch.setattr("app.domains.inventory.media_polling.poll_one_media_player_async", fake_poll_one)

    result = asyncio.run(poll_media_player_batch(players))

    assert len(result) == len(players)
    assert len({id(semaphore) for semaphore in seen_semaphores}) == 1


# -- finding a player at a new address ----------------------------------------


def _nettop(name: str, ip: str, **kwargs) -> MediaPlayer:
    return MediaPlayer(device_type="nettop", name=name, model="Nettop", ip_address=ip, **kwargs)


def _stub_relocation(monkeypatch, *, dns: dict[str, str], online: set[str], arp: dict[str, str], by_mac=None):
    async def fake_poll_one(player: MediaPlayer, *, port_scan_semaphore):
        return player.ip_address, LightMediaPollResult(is_online=player.ip_address in online)

    async def fake_resolve_by_mac(targets, *, session=None, subnets=None):
        return [
            MacRediscoveryMatch(target=t, normalized_mac=t.mac_address, new_ip=(by_mac or {})[t.mac_address])
            for t in targets
            if t.mac_address in (by_mac or {})
        ]

    monkeypatch.setattr(media_polling, "poll_one_media_player_async", fake_poll_one)
    monkeypatch.setattr(media_polling, "resolve_hostname", lambda name, **_kw: dns.get(name))
    monkeypatch.setattr(media_polling, "arp_mac_for_ip", arp.get)
    monkeypatch.setattr(media_polling, "resolve_devices_by_mac", fake_resolve_by_mac)


def test_relocate_follows_dns_and_corrects_a_wrong_mac(db_session, monkeypatch) -> None:
    # VNA-MUZ-901 took a new lease; the MAC on record belonged to something else,
    # which is why the MAC search never found it.
    player = _nettop("A9", "10.10.98.222", hostname="VNA-MUZ-901", mac_address="98:aa:fc:60:06:80", is_online=False)
    db_session.add(player)
    db_session.commit()
    _stub_relocation(
        monkeypatch,
        dns={"VNA-MUZ-901": "10.10.99.30"},
        online={"10.10.99.30"},
        arp={"10.10.99.30": "00:e0:4c:62:e3:20"},
    )

    moved = asyncio.run(
        media_polling._relocate_media_players(db_session, [player], mode="all", snapshot_source="test")
    )

    assert moved == 1
    assert player.ip_address == "10.10.99.30"
    assert player.is_online is True
    assert player.mac_address == "00:e0:4c:62:e3:20"


def test_relocate_by_dns_needs_the_player_to_answer(db_session, monkeypatch) -> None:
    player = _nettop("A5", "10.10.98.50", hostname="VNA-MUZ-501", is_online=False)
    db_session.add(player)
    db_session.commit()
    _stub_relocation(monkeypatch, dns={"VNA-MUZ-501": "10.10.98.60"}, online=set(), arp={})

    moved = asyncio.run(
        media_polling._relocate_media_players(db_session, [player], mode="all", snapshot_source="test")
    )

    assert moved == 0
    assert player.ip_address == "10.10.98.50"


def test_relocate_uses_a_hostname_typed_into_the_ip_field(db_session, monkeypatch) -> None:
    player = _nettop("A19", "VNA-MUZ-1901", hostname=None, is_online=False)
    db_session.add(player)
    db_session.commit()
    _stub_relocation(
        monkeypatch,
        dns={"VNA-MUZ-1901": "10.10.98.148"},
        online={"10.10.98.148"},
        arp={"10.10.98.148": "48:21:0b:58:a9:3c"},
    )

    asyncio.run(media_polling._relocate_media_players(db_session, [player], mode="all", snapshot_source="test"))

    assert player.ip_address == "10.10.98.148"
    assert player.mac_address == "48:21:0b:58:a9:3c"


def test_relocate_falls_back_to_mac_for_players_without_a_name(db_session, monkeypatch) -> None:
    player = MediaPlayer(
        device_type="iconbit", name="A2", model="Iconbit", ip_address="10.10.98.139",
        mac_address="98:aa:fc:60:b8:48", is_online=False,
    )
    taken = MediaPlayer(device_type="iconbit", name="A4", model="Iconbit", ip_address="10.10.99.75")
    db_session.add_all([player, taken])
    db_session.commit()
    _stub_relocation(
        monkeypatch, dns={}, online={"10.10.98.140"}, arp={}, by_mac={"98:aa:fc:60:b8:48": "10.10.98.140"}
    )

    moved = asyncio.run(
        media_polling._relocate_media_players(db_session, [player], mode="all", snapshot_source="test")
    )

    assert moved == 1
    assert player.ip_address == "10.10.98.140"
    assert player.is_online is True


def test_relocate_never_takes_another_players_address(db_session, monkeypatch) -> None:
    player = _nettop("A1", "10.10.98.251", hostname="VNA-MUZ-101", is_online=False)
    other = _nettop("A2", "10.10.98.139")
    db_session.add_all([player, other])
    db_session.commit()
    _stub_relocation(monkeypatch, dns={"VNA-MUZ-101": "10.10.98.139"}, online={"10.10.98.139"}, arp={})

    assert asyncio.run(
        media_polling._relocate_media_players(db_session, [player], mode="all", snapshot_source="test")
    ) == 0
    assert player.ip_address == "10.10.98.251"


def test_backfill_fills_only_missing_macs(monkeypatch) -> None:
    missing = _nettop("A12", "10.10.99.112")
    known = _nettop("A1", "10.10.98.251", mac_address="50:af:73:25:7b:17")
    monkeypatch.setattr(
        media_polling,
        "arp_mac_for_ip",
        {"10.10.99.112": "6C:4B:90:01:7D:34", "10.10.98.251": "11:22:33:44:55:66"}.get,
    )

    asyncio.run(media_polling._backfill_missing_macs([missing, known]))

    assert missing.mac_address == "6c:4b:90:01:7d:34"
    assert known.mac_address == "50:af:73:25:7b:17"


def test_poll_all_still_looks_for_players_behind_an_open_circuit(db_session, monkeypatch) -> None:
    player = _nettop("A9", "10.10.98.222", hostname="VNA-MUZ-901", is_online=False)
    db_session.add(player)
    db_session.commit()
    seen: list[str] = []

    async def circuit_open(kind, entity_id):
        return True

    async def fake_relocate(session, players, *, mode, snapshot_source):
        seen.extend(p.name for p in players)
        return 0

    monkeypatch.setattr(media_polling, "is_circuit_open", circuit_open)
    monkeypatch.setattr(media_polling, "_relocate_media_players", fake_relocate)
    monkeypatch.setattr(media_polling, "write_media_player_snapshot", lambda *a, **kw: None)

    asyncio.run(media_polling.poll_all_media_players_local(session=db_session))

    assert seen == ["A9"]
