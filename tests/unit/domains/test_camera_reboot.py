from __future__ import annotations

import asyncio

import pytest

from app.core.config import settings
from app.domains.inventory import camera_reboot
from app.domains.inventory.models import NetworkSwitch
from app.services.cisco_ssh import CameraPortInfo


@pytest.fixture
def switch(db_session) -> NetworkSwitch:
    row = NetworkSwitch(name="A25", ip_address="10.10.10.61", ssh_username="admin", ap_vlan=20, vendor="cisco")
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


class _LeaseRedis:
    """The few commands the switch write lease uses (fakeredis has no Lua here)."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, *, ex: int | None = None, nx: bool = False) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def exists(self, key: str) -> int:
        return int(key in self.values)

    async def eval(self, script: str, _keys: int, key: str, owner: str, *args) -> int:
        if self.values.get(key) != owner:
            return 0
        if "del" in script:
            del self.values[key]
        return 1


@pytest.fixture(autouse=True)
def lease_redis(monkeypatch) -> _LeaseRedis:
    from app.domains.inventory import switch_write_lock

    redis = _LeaseRedis()

    async def _get_redis():
        return redis

    monkeypatch.setattr(switch_write_lock, "get_redis", _get_redis)
    return redis


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(settings, "AUTO_REBOOT_AP_VERIFY_MAX_WAIT_SECONDS", 1)
    monkeypatch.setattr(settings, "AUTO_REBOOT_AP_VERIFY_POLL_INTERVAL_SECONDS", 1)
    monkeypatch.setattr(settings, "CAMERA_REBOOT_STAGGER_SECONDS", 0)


def _ports() -> list[CameraPortInfo]:
    return [
        CameraPortInfo(port="Gi1/0/1", vlan=247, oper_status="connected", poe_status="on", poe_power="15.4W"),
        # hung camera: no link, still drawing power - must be cycled
        CameraPortInfo(port="Gi1/0/2", vlan=247, oper_status="notconnect", poe_status="on", poe_power="4.0W"),
        # nothing plugged in
        CameraPortInfo(port="Gi1/0/3", vlan=247, oper_status="notconnect", poe_status="off", poe_power="0.0W"),
    ]


def test_is_empty_port_needs_both_no_link_and_no_power() -> None:
    connected, hung, empty = _ports()
    assert not camera_reboot.is_empty_port(connected)
    assert not camera_reboot.is_empty_port(hung)
    assert camera_reboot.is_empty_port(empty)


def test_reboot_all_cycles_cameras_one_at_a_time_and_skips_empty_ports(db_session, switch, monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(camera_reboot, "get_camera_ports", lambda *_a, **_kw: _ports())
    monkeypatch.setattr(
        camera_reboot, "poe_cycle_ports_bulk", lambda *args: calls.append(list(args[-1])) or True
    )

    result = asyncio.run(camera_reboot.reboot_all_cameras(db_session, switch))

    # never one call powering several cameras off together
    assert calls == [["Gi1/0/1"], ["Gi1/0/2"]]
    assert result["status"] == "done"
    assert result["rebooted_count"] == 2
    assert result["skipped_empty"] == 1
    # Gi1/0/2 stays "notconnect" in the fake, so it never comes back
    assert result["back_online_count"] == 1
    assert result["not_back_ports"] == ["Gi1/0/2"]


def test_reboot_all_continues_past_a_single_port_failure(db_session, switch, monkeypatch) -> None:
    monkeypatch.setattr(camera_reboot, "get_camera_ports", lambda *_a, **_kw: _ports())
    monkeypatch.setattr(camera_reboot, "poe_cycle_ports_bulk", lambda *args: args[-1] != ["Gi1/0/1"])

    result = asyncio.run(camera_reboot.reboot_all_cameras(db_session, switch))

    assert result["rebooted_count"] == 1
    assert result["failed_ports"] == ["Gi1/0/1"]


def test_reboot_all_waits_its_turn_behind_another_switch_write(db_session, switch, monkeypatch, lease_redis) -> None:
    def _must_not_cycle(*_a):
        raise AssertionError("must not touch a switch another operation holds")

    monkeypatch.setattr(camera_reboot, "poe_cycle_ports_bulk", _must_not_cycle)
    lease_redis.values[f"lock:switch-write:{switch.id}"] = "someone-else"

    assert asyncio.run(camera_reboot.reboot_all_cameras(db_session, switch))["status"] == "busy"


def test_reboot_all_releases_the_switch_afterwards(db_session, switch, monkeypatch, lease_redis) -> None:
    monkeypatch.setattr(camera_reboot, "get_camera_ports", lambda *_a, **_kw: _ports())
    monkeypatch.setattr(camera_reboot, "poe_cycle_ports_bulk", lambda *_a: True)

    asyncio.run(camera_reboot.reboot_all_cameras(db_session, switch))

    assert lease_redis.values == {}


def test_reboot_all_refuses_where_hardware_writes_are_off(db_session, switch, monkeypatch, lease_redis) -> None:
    monkeypatch.setattr(settings, "ALLOW_HARDWARE_WRITES", False)

    def _must_not_cycle(*_a):
        raise AssertionError("no equipment writes on this instance")

    monkeypatch.setattr(camera_reboot, "poe_cycle_ports_bulk", _must_not_cycle)

    assert asyncio.run(camera_reboot.reboot_all_cameras(db_session, switch))["status"] == "hardware_writes_disabled"
    assert lease_redis.values == {}
