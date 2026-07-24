from __future__ import annotations

from app.services.cisco_ssh import get_camera_ports

_STATUS_OUTPUT = """
Port      Name               Status       Vlan       Duplex  Speed Type
Gi2/0/14                     connected    247        a-full  a-100 10/100/1000BaseTX
Gi2/0/20                     notconnect   1          auto    auto  10/100/1000BaseTX
Gi3/0/1   Camera-Entrance    connected    244        a-full  a-100 10/100/1000BaseTX
Gi2/0/47                     connected    20         a-full  a-100 10/100/1000BaseTX
"""

_POE_OUTPUT = """
Interface Admin  Oper       Power   Device              Class Max
--------- ------ ---------- ------- ------------------- ----- ----
Gi2/0/14  auto   on         15.4    n/a                 3     30.0
Gi3/0/1   auto   on         7.0     n/a                 2     30.0
Gi2/0/47  auto   on         15.4    AIR-CAP2602I-R-K9    3     30.0
"""


class _FakeSSH:
    def __init__(self, *, connect_ok: bool, fail_on: str | None = None) -> None:
        self._connect_ok = connect_ok
        self._fail_on = fail_on
        self.closed = False

    def connect(self) -> bool:
        return self._connect_ok

    def execute(self, cmd: str) -> str:
        if self._fail_on and cmd.startswith(self._fail_on):
            raise RuntimeError("simulated SSH failure")
        if cmd == "show interfaces status":
            return _STATUS_OUTPUT
        if cmd == "show power inline":
            return _POE_OUTPUT
        return ""

    def close(self) -> None:
        self.closed = True


def test_get_camera_ports_returns_none_when_ssh_connect_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.cisco_ssh.CiscoSSH",
        lambda *a, **kw: _FakeSSH(connect_ok=False),
    )
    assert get_camera_ports("10.0.0.1", "admin", "pass", "enable", 22, {241, 244, 247}) is None


def test_get_camera_ports_returns_none_when_status_command_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.cisco_ssh.CiscoSSH",
        lambda *a, **kw: _FakeSSH(connect_ok=True, fail_on="show interfaces status"),
    )
    assert get_camera_ports("10.0.0.1", "admin", "pass", "enable", 22, {241, 244, 247}) is None


def test_get_camera_ports_filters_by_vlan_and_enriches_poe(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.cisco_ssh.CiscoSSH",
        lambda *a, **kw: _FakeSSH(connect_ok=True),
    )
    result = get_camera_ports("10.0.0.1", "admin", "pass", "enable", 22, {241, 244, 247})

    assert result is not None
    ports = {p.port: p for p in result}
    # VLAN 20 (AP vlan) and the notconnect port must not appear - only 247/244.
    assert set(ports) == {"Gi2/0/14", "Gi3/0/1"}
    assert ports["Gi2/0/14"].vlan == 247
    assert ports["Gi2/0/14"].poe_power == "15.4W"
    assert ports["Gi3/0/1"].vlan == 244
    assert ports["Gi3/0/1"].description == "Camera-Entrance"
    assert ports["Gi3/0/1"].poe_power == "7.0W"


def test_get_camera_ports_survives_poe_enrichment_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.cisco_ssh.CiscoSSH",
        lambda *a, **kw: _FakeSSH(connect_ok=True, fail_on="show power inline"),
    )
    result = get_camera_ports("10.0.0.1", "admin", "pass", "enable", 22, {244, 247})

    assert result is not None
    assert len(result) == 2
    assert all(p.poe_power is None for p in result)
