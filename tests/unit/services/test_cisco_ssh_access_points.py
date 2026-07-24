from __future__ import annotations

from app.services.cisco_ssh import get_access_points

_CDP_ONE_AP = """
-------------------------
Device ID: AP-FLOOR-01
Interface: GigabitEthernet1/0/10, Port ID (outgoing port): GigabitEthernet0
Platform: cisco C9120AXI-R, Capabilities: Router Switch IGMP Trans-Bridge
IP address: 10.10.20.10
"""


class _FakeSSH:
    def __init__(self, *, connect_ok: bool, cdp_output: str = "", fail_on: str | None = None) -> None:
        self._connect_ok = connect_ok
        self._cdp_output = cdp_output
        self._fail_on = fail_on
        self.closed = False

    def connect(self) -> bool:
        return self._connect_ok

    def execute(self, cmd: str) -> str:
        if self._fail_on and cmd.startswith(self._fail_on):
            raise RuntimeError("simulated SSH failure")
        if cmd == "show cdp neighbors detail":
            return self._cdp_output
        return ""

    def close(self) -> None:
        self.closed = True


def test_get_access_points_returns_none_when_ssh_connect_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.cisco_ssh.CiscoSSH",
        lambda *a, **kw: _FakeSSH(connect_ok=False),
    )
    assert get_access_points("10.0.0.1", "admin", "pass") is None


def test_get_access_points_returns_none_when_cdp_command_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.cisco_ssh.CiscoSSH",
        lambda *a, **kw: _FakeSSH(connect_ok=True, fail_on="show cdp neighbors detail"),
    )
    assert get_access_points("10.0.0.1", "admin", "pass") is None


def test_get_access_points_returns_empty_list_for_a_genuinely_clean_scan(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.cisco_ssh.CiscoSSH",
        lambda *a, **kw: _FakeSSH(connect_ok=True, cdp_output="no neighbors here"),
    )
    result = get_access_points("10.0.0.1", "admin", "pass")
    assert result == []


def test_get_access_points_keeps_aps_when_an_enrichment_step_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.cisco_ssh.CiscoSSH",
        lambda *a, **kw: _FakeSSH(connect_ok=True, cdp_output=_CDP_ONE_AP, fail_on="show power inline"),
    )
    result = get_access_points("10.0.0.1", "admin", "pass", vlan=20)
    assert result is not None
    assert len(result) == 1
    assert result[0].cdp_name == "AP-FLOOR-01"
