from dataclasses import dataclass
from time import monotonic

import pytest
from fastapi.testclient import TestClient

from app.api.routes.switches import _shared as switch_shared
from app.api.routes.switches import access_points as switch_access_points
from app.api.routes.switches import ports as switch_ports
from app.core.config import settings
from app.domains.inventory import switch_polling
from app.services.cisco_ssh import CameraPortInfo
from app.services.switches.base import SwitchPollInfo, SwitchPortState


@dataclass
class _SwitchInfo:
    hostname: str | None = "SW-01"
    model_info: str | None = "WS-C2960X"
    ios_version: str | None = "15.2(7)E"
    uptime: str | None = "2д 5ч"
    is_online: bool = True


class _FakeRedis:
    def __init__(self):
        self._values: dict[str, tuple[str, float | None]] = {}

    def _is_expired(self, key: str) -> bool:
        value = self._values.get(key)
        if value is None:
            return True
        _, expires_at = value
        if expires_at is None or expires_at > monotonic():
            return False
        self._values.pop(key, None)
        return True

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False):
        if nx and not self._is_expired(key):
            return False
        expires_at = monotonic() + ex if ex else None
        self._values[key] = (value, expires_at)
        return True

    async def delete(self, *keys: str):
        for key in keys:
            self._values.pop(key, None)
        return len(keys)

    async def eval(self, script: str, _keys: int, key: str, owner: str, *args) -> int:
        if self._is_expired(key) or self._values.get(key, (None, None))[0] != owner:
            return 0
        if "del" in script:
            self._values.pop(key, None)
            return 1
        if "expire" in script:
            self._values[key] = (owner, monotonic() + int(args[0]))
            return 1
        return 0


@pytest.fixture(autouse=True)
def _switch_write_redis(monkeypatch):
    """Hardware-write tests must model the production Redis safety lease."""
    redis = _FakeRedis()

    async def _get_redis():
        return redis

    monkeypatch.setattr(switch_shared, "get_redis", _get_redis)


def test_create_and_poll_switch(client: TestClient, admin_token: str, monkeypatch):
    class _Provider:
        def poll_switch(self, _switch):
            info = _SwitchInfo()
            return SwitchPollInfo(
                is_online=info.is_online,
                hostname=info.hostname,
                model_info=info.model_info,
                ios_version=info.ios_version,
                uptime=info.uptime,
            )

        def get_ports(self, _switch):
            return []

        def set_admin_state(self, _switch, _port, _state):
            return None

        def set_description(self, _switch, _port, _description):
            return None

        def set_vlan(self, _switch, _port, _vlan):
            return None

        def set_poe(self, _switch, _port, _action):
            return None

    monkeypatch.setattr(switch_polling, "resolve_switch_provider", lambda *_args, **_kwargs: _Provider())

    created = client.post(
        "/api/v1/switches/",
        json={
            "name": "Main Switch",
            "ip_address": "10.10.10.30",
            "ssh_username": "admin",
            "ssh_password": "admin",
            "enable_password": "admin",
            "ssh_port": 22,
            "ap_vlan": 20,
            "vendor": "cisco",
            "management_protocol": "snmp+ssh",
            "snmp_version": "2c",
            "snmp_community_ro": "public",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 200
    assert "snmp_community_ro" not in created.json()
    assert "snmp_community_rw" not in created.json()
    switch_id = created.json()["id"]

    polled = client.post(
        f"/api/v1/switches/{switch_id}/poll",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert polled.status_code == 200
    assert polled.json()["is_online"] is True
    assert "snmp_community_ro" not in polled.json()
    assert "snmp_community_rw" not in polled.json()


def test_switch_ports_read_and_write(
    client: TestClient,
    admin_token: str,
    user_token: str,
    monkeypatch,
):
    class _Provider:
        def poll_switch(self, _switch):
            return SwitchPollInfo(is_online=True)

        def get_ports(self, _switch):
            return [
                SwitchPortState(
                    port="Gi0/1",
                    if_index=1,
                    description="AP uplink",
                    admin_status="up",
                    oper_status="up",
                    speed_mbps=1000,
                    vlan=20,
                    poe_enabled=True,
                )
            ]

        def set_admin_state(self, _switch, _port, _state):
            return None

        def set_description(self, _switch, _port, _description):
            return None

        def set_vlan(self, _switch, _port, _vlan):
            return None

        def set_poe(self, _switch, _port, _action):
            return None

    monkeypatch.setattr(switch_ports, "resolve_switch_provider", lambda *_args, **_kwargs: _Provider())

    created = client.post(
        "/api/v1/switches/",
        json={
            "name": "D-Link Floor 1",
            "ip_address": "10.10.10.40",
            "ssh_username": "admin",
            "ssh_password": "admin",
            "enable_password": "",
            "ssh_port": 22,
            "ap_vlan": 20,
            "vendor": "dlink",
            "management_protocol": "snmp",
            "snmp_version": "2c",
            "snmp_community_ro": "public",
            "snmp_community_rw": "private",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 200
    switch_id = created.json()["id"]

    read_ports = client.get(
        f"/api/v1/switches/{switch_id}/ports",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert read_ports.status_code == 200
    assert read_ports.json()["count"] == 1
    assert read_ports.json()["data"][0]["port"] == "Gi0/1"

    forbidden_write = client.post(
        f"/api/v1/switches/{switch_id}/ports/Gi0%2F1/vlan",
        json={"vlan": 100},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert forbidden_write.status_code == 403

    write_ok = client.post(
        f"/api/v1/switches/{switch_id}/ports/Gi0%2F1/vlan",
        json={"vlan": 100},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert write_ok.status_code == 200


def test_switch_port_write_runs_the_provider_in_process(client: TestClient, admin_token: str, monkeypatch):
    calls: list[tuple] = []

    class _Provider:
        def set_vlan(self, _switch, port, vlan):
            calls.append((port, vlan))

    monkeypatch.setattr(switch_ports, "resolve_switch_provider", lambda _switch: _Provider())

    created = client.post(
        "/api/v1/switches/",
        json={
            "name": "SW-Local",
            "ip_address": "10.10.10.41",
            "ssh_username": "admin",
            "ssh_password": "admin",
            "enable_password": "",
            "ssh_port": 22,
            "ap_vlan": 20,
            "vendor": "dlink",
            "management_protocol": "snmp",
            "snmp_version": "2c",
            "snmp_community_ro": "public",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 200
    switch_id = created.json()["id"]

    write_resp = client.post(
        f"/api/v1/switches/{switch_id}/ports/Gi0%2F1/vlan",
        json={"vlan": 100},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert write_resp.status_code == 200
    assert write_resp.json()["message"] == "ok"
    assert calls == [("Gi0/1", 100)]


def test_switch_write_rejects_unsafe_port_identifier(client: TestClient, admin_token: str, monkeypatch):
    class _Provider:
        def poll_switch(self, _switch):
            return SwitchPollInfo(is_online=True)

        def get_ports(self, _switch):
            return []

        def set_vlan(self, _switch, _port, _vlan):
            return None

    fake_redis = _FakeRedis()

    async def _fake_get_redis():
        return fake_redis

    monkeypatch.setattr(switch_ports, "resolve_switch_provider", lambda *_args, **_kwargs: _Provider())
    monkeypatch.setattr(switch_shared, "get_redis", _fake_get_redis)

    created = client.post(
        "/api/v1/switches/",
        json={
            "name": "SW-Safe-Port",
            "ip_address": "10.10.10.42",
            "ssh_username": "admin",
            "ssh_password": "admin",
            "enable_password": "",
            "ssh_port": 22,
            "ap_vlan": 20,
            "vendor": "dlink",
            "management_protocol": "snmp",
            "snmp_version": "2c",
            "snmp_community_ro": "public",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 200
    switch_id = created.json()["id"]

    write_resp = client.post(
        f"/api/v1/switches/{switch_id}/ports/Gi0%2F1%20%3Breload/vlan",
        json={"vlan": 100},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert write_resp.status_code == 422


def test_switch_poe_cycle_is_rate_limited_by_cooldown(client: TestClient, admin_token: str, monkeypatch):
    calls: list[tuple[str, str]] = []

    class _Provider:
        def poll_switch(self, _switch):
            return SwitchPollInfo(is_online=True)

        def get_ports(self, _switch):
            return []

        def set_poe(self, _switch, port, action):
            calls.append((port, action))
            return

    fake_redis = _FakeRedis()

    async def _fake_get_redis():
        return fake_redis

    monkeypatch.setattr(switch_ports, "resolve_switch_provider", lambda *_args, **_kwargs: _Provider())
    monkeypatch.setattr(settings, "SWITCH_SAFETY_COOLDOWN_SECONDS", 60)
    monkeypatch.setattr(switch_shared, "get_redis", _fake_get_redis)

    created = client.post(
        "/api/v1/switches/",
        json={
            "name": "SW-Cooldown",
            "ip_address": "10.10.10.43",
            "ssh_username": "admin",
            "ssh_password": "admin",
            "enable_password": "",
            "ssh_port": 22,
            "ap_vlan": 20,
            "vendor": "dlink",
            "management_protocol": "snmp",
            "snmp_version": "2c",
            "snmp_community_ro": "public",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 200
    switch_id = created.json()["id"]

    first = client.post(
        f"/api/v1/switches/{switch_id}/ports/Gi0%2F1/poe",
        json={"action": "cycle"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    second = client.post(
        f"/api/v1/switches/{switch_id}/ports/Gi0%2F1/poe",
        json={"action": "cycle"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert first.status_code == 200
    assert second.status_code == 429
    assert calls == [("Gi0/1", "cycle")]


def test_reboot_all_cameras_requires_superuser(client: TestClient, admin_token: str, user_token: str):
    created = client.post(
        "/api/v1/switches/",
        json={
            "name": "SW-Cameras-Guard",
            "ip_address": "10.10.10.60",
            "ssh_username": "admin",
            "ssh_password": "admin",
            "enable_password": "",
            "ssh_port": 22,
            "ap_vlan": 20,
            "vendor": "cisco",
            "management_protocol": "snmp+ssh",
            "snmp_version": "2c",
            "snmp_community_ro": "public",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 200
    switch_id = created.json()["id"]

    response = client.post(
        f"/api/v1/switches/{switch_id}/camera-ports/reboot-all",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 403


def test_reboot_all_cameras_cycles_one_camera_at_a_time(client: TestClient, admin_token: str, monkeypatch):
    monkeypatch.setattr(settings, "AUTO_REBOOT_AP_VERIFY_MAX_WAIT_SECONDS", 1)
    monkeypatch.setattr(settings, "AUTO_REBOOT_AP_VERIFY_POLL_INTERVAL_SECONDS", 1)
    monkeypatch.setattr(settings, "CAMERA_REBOOT_STAGGER_SECONDS", 0)
    calls: list[list[str]] = []

    def _fake_get_camera_ports(*_args, **_kwargs):
        return [
            CameraPortInfo(port="Gi0/10", vlan=241, oper_status="connected"),
            CameraPortInfo(port="Gi0/11", vlan=241, oper_status="notconnect"),
        ]

    def _fake_poe_cycle_bulk(_ip, _user, _pw, _enable, _port, interfaces):
        calls.append(list(interfaces))
        return True

    monkeypatch.setattr(switch_access_points, "get_camera_ports", _fake_get_camera_ports)
    monkeypatch.setattr(switch_access_points, "poe_cycle_ports_bulk", _fake_poe_cycle_bulk)

    created = client.post(
        "/api/v1/switches/",
        json={
            "name": "SW-Cameras",
            "ip_address": "10.10.10.61",
            "ssh_username": "admin",
            "ssh_password": "admin",
            "enable_password": "",
            "ssh_port": 22,
            "ap_vlan": 20,
            "vendor": "cisco",
            "management_protocol": "snmp+ssh",
            "snmp_version": "2c",
            "snmp_community_ro": "public",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 200
    switch_id = created.json()["id"]

    response = client.post(
        f"/api/v1/switches/{switch_id}/camera-ports/reboot-all",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    # Gi0/10 is already "connected" in the fake, so verification finds it
    # back online; Gi0/11 stays "notconnect" and never resolves.
    assert response.json() == {
        "status": "rebooting",
        "rebooted_count": 2,
        "failed_count": 0,
        "back_online_count": 1,
    }
    # Each camera is cycled in its own call, one port at a time - never a
    # single call powering multiple cameras off together.
    assert calls == [["Gi0/10"], ["Gi0/11"]]


def test_reboot_all_cameras_continues_past_a_single_port_failure(client: TestClient, admin_token: str, monkeypatch):
    monkeypatch.setattr(settings, "AUTO_REBOOT_AP_VERIFY_MAX_WAIT_SECONDS", 1)
    monkeypatch.setattr(settings, "AUTO_REBOOT_AP_VERIFY_POLL_INTERVAL_SECONDS", 1)
    monkeypatch.setattr(settings, "CAMERA_REBOOT_STAGGER_SECONDS", 0)

    def _fake_get_camera_ports(*_args, **_kwargs):
        return [
            CameraPortInfo(port="Gi0/20", vlan=241, oper_status="connected"),
            CameraPortInfo(port="Gi0/21", vlan=241, oper_status="connected"),
        ]

    def _fake_poe_cycle_bulk(_ip, _user, _pw, _enable, _port, interfaces):
        return interfaces != ["Gi0/20"]

    monkeypatch.setattr(switch_access_points, "get_camera_ports", _fake_get_camera_ports)
    monkeypatch.setattr(switch_access_points, "poe_cycle_ports_bulk", _fake_poe_cycle_bulk)

    created = client.post(
        "/api/v1/switches/",
        json={
            "name": "SW-Cameras-Partial",
            "ip_address": "10.10.10.64",
            "ssh_username": "admin",
            "ssh_password": "admin",
            "enable_password": "",
            "ssh_port": 22,
            "ap_vlan": 20,
            "vendor": "cisco",
            "management_protocol": "snmp+ssh",
            "snmp_version": "2c",
            "snmp_community_ro": "public",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 200
    switch_id = created.json()["id"]

    response = client.post(
        f"/api/v1/switches/{switch_id}/camera-ports/reboot-all",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "rebooting",
        "rebooted_count": 1,
        "failed_count": 1,
        "back_online_count": 1,
    }


def test_reboot_camera_port_reports_back_online_status(client: TestClient, admin_token: str, monkeypatch):
    monkeypatch.setattr(settings, "AUTO_REBOOT_AP_VERIFY_MAX_WAIT_SECONDS", 1)
    monkeypatch.setattr(settings, "AUTO_REBOOT_AP_VERIFY_POLL_INTERVAL_SECONDS", 1)
    calls: list[list[str]] = []

    def _fake_get_camera_ports(*_args, **_kwargs):
        return [CameraPortInfo(port="Gi0/12", vlan=241, oper_status="connected")]

    def _fake_poe_cycle_bulk(_ip, _user, _pw, _enable, _port, interfaces):
        calls.append(list(interfaces))
        return True

    monkeypatch.setattr(switch_access_points, "get_camera_ports", _fake_get_camera_ports)
    monkeypatch.setattr(switch_access_points, "poe_cycle_ports_bulk", _fake_poe_cycle_bulk)

    created = client.post(
        "/api/v1/switches/",
        json={
            "name": "SW-Camera-Single",
            "ip_address": "10.10.10.62",
            "ssh_username": "admin",
            "ssh_password": "admin",
            "enable_password": "",
            "ssh_port": 22,
            "ap_vlan": 20,
            "vendor": "cisco",
            "management_protocol": "snmp+ssh",
            "snmp_version": "2c",
            "snmp_community_ro": "public",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 200
    switch_id = created.json()["id"]

    response = client.post(
        f"/api/v1/switches/{switch_id}/camera-ports/Gi0%2F12/reboot",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "rebooting", "port": "Gi0/12", "back_online": True}
    assert calls == [["Gi0/12"]]


def test_reboot_camera_port_requires_superuser(client: TestClient, admin_token: str, user_token: str):
    created = client.post(
        "/api/v1/switches/",
        json={
            "name": "SW-Camera-Guard",
            "ip_address": "10.10.10.63",
            "ssh_username": "admin",
            "ssh_password": "admin",
            "enable_password": "",
            "ssh_port": 22,
            "ap_vlan": 20,
            "vendor": "cisco",
            "management_protocol": "snmp+ssh",
            "snmp_version": "2c",
            "snmp_community_ro": "public",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 200
    switch_id = created.json()["id"]

    response = client.post(
        f"/api/v1/switches/{switch_id}/camera-ports/Gi0%2F12/reboot",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 403


def test_reboot_ap_verifies_and_reports_back_online_when_mac_address_given(
    client: TestClient, admin_token: str, monkeypatch
):
    monkeypatch.setattr(switch_access_points, "poe_cycle_ap", lambda *a, **kw: True)

    async def _fake_verify(_switch, mac_address):
        assert mac_address == "aa:bb:cc:dd:ee:ff"
        return True

    monkeypatch.setattr(switch_access_points, "_verify_ap_back_online", _fake_verify)

    created = client.post(
        "/api/v1/switches/",
        json={
            "name": "SW-AP-Verify",
            "ip_address": "10.10.10.70",
            "ssh_username": "admin",
            "ssh_password": "admin",
            "enable_password": "",
            "ssh_port": 22,
            "ap_vlan": 20,
            "vendor": "cisco",
            "management_protocol": "snmp+ssh",
            "snmp_version": "2c",
            "snmp_community_ro": "public",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 200
    switch_id = created.json()["id"]

    response = client.post(
        f"/api/v1/switches/{switch_id}/reboot-ap",
        json={"interface": "Gi0/1", "mac_address": "aa:bb:cc:dd:ee:ff"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "rebooting", "interface": "Gi0/1", "method": "poe", "back_online": True}


def test_reboot_ap_skips_verification_without_mac_address(client: TestClient, admin_token: str, monkeypatch):
    monkeypatch.setattr(switch_access_points, "poe_cycle_ap", lambda *a, **kw: True)

    def _must_not_be_called(*_a, **_kw):
        raise AssertionError("verification must not run without a mac_address")

    monkeypatch.setattr(switch_access_points, "_verify_ap_back_online", _must_not_be_called)

    created = client.post(
        "/api/v1/switches/",
        json={
            "name": "SW-AP-No-Verify",
            "ip_address": "10.10.10.71",
            "ssh_username": "admin",
            "ssh_password": "admin",
            "enable_password": "",
            "ssh_port": 22,
            "ap_vlan": 20,
            "vendor": "cisco",
            "management_protocol": "snmp+ssh",
            "snmp_version": "2c",
            "snmp_community_ro": "public",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 200
    switch_id = created.json()["id"]

    response = client.post(
        f"/api/v1/switches/{switch_id}/reboot-ap",
        json={"interface": "Gi0/1"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "rebooting", "interface": "Gi0/1", "method": "poe"}


def test_reboot_ap_is_superuser_only(client: TestClient, admin_token: str, user_token: str):
    """The UI has always hidden the AP reboot button from non-superusers, but
    the endpoint accepted any authenticated session - so the restriction only
    existed in the browser and a PoE cycle on a live access point was one API
    call away for any user. Every other hardware-power-cycling endpoint here
    (camera-ports/reboot, camera-ports/reboot-all) is superuser-only; this one
    has to match.
    """
    created = client.post(
        "/api/v1/switches/",
        json={
            "name": "AP reboot authz",
            "ip_address": "10.10.10.77",
            "ssh_username": "admin",
            "ssh_password": "admin",
            "enable_password": "",
            "ssh_port": 22,
            "ap_vlan": 20,
            "vendor": "cisco",
            "management_protocol": "ssh",
            "snmp_version": "2c",
            "snmp_community_ro": "public",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 200
    switch_id = created.json()["id"]

    forbidden = client.post(
        f"/api/v1/switches/{switch_id}/reboot-ap",
        json={"interface": "GigabitEthernet1/0/47", "method": "poe"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert forbidden.status_code == 403, (
        "a non-superuser must not be able to power-cycle an access point"
    )


def _create_dlink_switch(client: TestClient, admin_token: str, ip: str = "10.10.10.61") -> str:
    created = client.post(
        "/api/v1/switches/",
        json={
            "name": f"SW-{ip}",
            "ip_address": ip,
            "ssh_username": "admin",
            "ssh_password": "admin",
            "enable_password": "",
            "ssh_port": 22,
            "ap_vlan": 20,
            "vendor": "dlink",
            "management_protocol": "snmp",
            "snmp_version": "2c",
            "snmp_community_ro": "public",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 200
    return created.json()["id"]


def test_port_write_is_superuser_only_and_never_reaches_the_provider(
    client: TestClient, admin_token: str, user_token: str, monkeypatch
):
    """These writes used to be reachable in two ways (in-process, or through the
    network-control service); the in-process path is now the only one, so its
    guards are what stands between an ordinary login and a live switch."""
    calls: list[tuple] = []

    class _Provider:
        def set_vlan(self, _switch, port, vlan):
            calls.append((port, vlan))

    monkeypatch.setattr(switch_ports, "resolve_switch_provider", lambda _switch: _Provider())
    switch_id = _create_dlink_switch(client, admin_token)

    response = client.post(
        f"/api/v1/switches/{switch_id}/ports/Gi0%2F1/vlan",
        json={"vlan": 100},
        headers={"Authorization": f"Bearer {user_token}"},
    )

    assert response.status_code in (401, 403)
    assert calls == []


def test_port_write_is_rejected_with_409_while_another_write_holds_the_switch_lock(
    client: TestClient, admin_token: str, monkeypatch
):
    import asyncio

    calls: list[tuple] = []

    class _Provider:
        def set_vlan(self, _switch, port, vlan):
            calls.append((port, vlan))

    monkeypatch.setattr(switch_ports, "resolve_switch_provider", lambda _switch: _Provider())
    switch_id = _create_dlink_switch(client, admin_token, "10.10.10.62")

    async def _hold():
        # this module swaps switch_shared.get_redis for a private fake (see the
        # autouse _switch_write_redis fixture), so take the lock through it
        r = await switch_shared.get_redis()
        await r.set(f"lock:switch-write:{switch_id}", "someone-else", ex=60)

    asyncio.run(_hold())

    response = client.post(
        f"/api/v1/switches/{switch_id}/ports/Gi0%2F1/vlan",
        json={"vlan": 100},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 409
    assert calls == []


def test_port_write_fails_closed_when_the_safety_lock_cannot_be_taken(client: TestClient, admin_token: str, monkeypatch):
    """No Redis means no distributed lock, and a process-local fallback would let
    two API workers power-cycle the same switch at once - so it must refuse."""
    from app.api.routes.switches import _shared

    calls: list[tuple] = []

    class _Provider:
        def set_vlan(self, _switch, port, vlan):
            calls.append((port, vlan))

    async def _no_redis():
        raise ConnectionError("redis down")

    monkeypatch.setattr(switch_ports, "resolve_switch_provider", lambda _switch: _Provider())
    switch_id = _create_dlink_switch(client, admin_token, "10.10.10.63")
    monkeypatch.setattr(_shared, "get_redis", _no_redis)

    response = client.post(
        f"/api/v1/switches/{switch_id}/ports/Gi0%2F1/vlan",
        json={"vlan": 100},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 503
    assert calls == []
