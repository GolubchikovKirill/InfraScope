from __future__ import annotations

from app.models import NetworkSwitch
from app.services.cisco_ssh import CiscoSSH
from app.services.switches.cisco_provider import CiscoSwitchProvider


def _build_switch() -> NetworkSwitch:
    return NetworkSwitch(
        name="sw1",
        ip_address="10.0.0.10",
        ssh_username="admin",
        ssh_password="pass",
        enable_password="enable",
        ssh_port=22,
    )


def test_get_ports_uses_single_ssh_session(monkeypatch):
    provider = CiscoSwitchProvider()
    switch = _build_switch()

    class _FakeSSH:
        connect_calls = 0
        close_calls = 0

        def __init__(self, *_args, **_kwargs):
            self.commands: list[str] = []

        def connect(self):
            _FakeSSH.connect_calls += 1
            return True

        def execute(self, cmd: str):
            self.commands.append(cmd)
            if cmd == "show interfaces status":
                return "Gi1/0/1 -- connected 1 a-full a-100 10/100/1000-TX"
            if cmd == "show interfaces switchport":
                return "Name: Gi1/0/1\nAdministrative Mode: static access\nAccess Mode VLAN: 1\n"
            return ""

        def close(self):
            _FakeSSH.close_calls += 1

    monkeypatch.setattr("app.services.switches.cisco_provider.CiscoSSH", _FakeSSH)
    monkeypatch.setattr(provider.snmp_provider, "get_ports", lambda _sw: [])

    ports = provider.get_ports(switch)

    assert _FakeSSH.connect_calls == 1
    assert _FakeSSH.close_calls == 1
    assert len(ports) == 1


def test_set_poe_cycle_uses_single_session(monkeypatch):
    provider = CiscoSwitchProvider()
    switch = _build_switch()

    class _FakeSSH:
        connect_calls = 0
        close_calls = 0
        commands: list[str] = []

        def __init__(self, *_args, **_kwargs):
            pass

        def connect(self):
            _FakeSSH.connect_calls += 1
            return True

        def execute(self, cmd: str):
            _FakeSSH.commands.append(cmd)
            return ""

        def close(self):
            _FakeSSH.close_calls += 1

    monkeypatch.setattr("app.services.switches.cisco_provider.CiscoSSH", _FakeSSH)

    provider.set_poe(switch, "Gi1/0/1", "cycle")

    assert _FakeSSH.connect_calls == 1
    assert _FakeSSH.close_calls == 1
    assert "power inline never" in _FakeSSH.commands
    assert "power inline auto" in _FakeSSH.commands


def test_cisco_ssh_close_closes_channel_and_transport():
    class _FakeShell:
        def __init__(self):
            self.sent: list[str] = []
            self.closed = False

        def send(self, data: str):
            self.sent.append(data)

        def close(self):
            self.closed = True

    class _FakeTransport:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class _FakeClient:
        def __init__(self):
            self.transport = _FakeTransport()
            self.closed = False

        def get_transport(self):
            return self.transport

        def close(self):
            self.closed = True

    ssh = CiscoSSH("10.0.0.10", "admin", "pass")
    shell = _FakeShell()
    client = _FakeClient()
    ssh.shell = shell  # type: ignore[assignment]
    ssh.client = client  # type: ignore[assignment]

    ssh.close()

    assert shell.closed is True
    assert "exit\n" in shell.sent
    assert client.transport.closed is True
    assert client.closed is True
