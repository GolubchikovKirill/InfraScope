from __future__ import annotations

from app.models import NetworkSwitch
from app.services import cisco_ssh as cisco_ssh_module
from app.services.cisco_ssh import CiscoSSH, get_access_points
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
                # Real Cisco output column-aligns with multiple spaces, incl.
                # when the Name field is empty - a single-space fixture here
                # would mask a real parser bug (see test_cisco_ssh_parsers.py).
                return "Gi1/0/1                      connected    1          a-full  a-100 10/100/1000-TX"
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
    assert ports[0].port == "Gi1/0/1"
    assert ports[0].vlan == 1
    assert ports[0].description is None


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


def test_connect_remembers_the_auth_method_that_worked(monkeypatch):
    """The auth-method probe is a whole extra TCP+SSH handshake, and a switch
    answers it identically every time. Paying it on every connect doubled the
    connection cost of every operation."""
    cisco_ssh_module._AUTH_METHOD_CACHE.clear()
    probe_calls = 0

    def _probe(_self):
        nonlocal probe_calls
        probe_calls += 1
        return ["password"]

    monkeypatch.setattr(CiscoSSH, "_query_auth_methods", _probe)
    monkeypatch.setattr(CiscoSSH, "_connect_password", lambda _self: True)

    assert CiscoSSH("10.0.0.10", "admin", "pass").connect() is True
    assert probe_calls == 1

    assert CiscoSSH("10.0.0.10", "admin", "pass").connect() is True
    assert probe_calls == 1


def test_connect_reprobes_when_the_remembered_method_stops_working(monkeypatch):
    cisco_ssh_module._AUTH_METHOD_CACHE.clear()
    cisco_ssh_module._AUTH_METHOD_CACHE[("10.0.0.11", 22, "admin")] = "password"
    probe_calls = 0

    def _probe(_self):
        nonlocal probe_calls
        probe_calls += 1
        return ["keyboard-interactive"]

    monkeypatch.setattr(CiscoSSH, "_query_auth_methods", _probe)
    monkeypatch.setattr(CiscoSSH, "_connect_password", lambda _self: False)
    monkeypatch.setattr(CiscoSSH, "_connect_keyboard_interactive", lambda _self: True)

    assert CiscoSSH("10.0.0.11", "admin", "pass").connect() is True
    assert probe_calls == 1
    assert cisco_ssh_module._AUTH_METHOD_CACHE[("10.0.0.11", 22, "admin")] == "keyboard-interactive"
    cisco_ssh_module._AUTH_METHOD_CACHE.clear()


def test_get_access_points_reuses_a_caller_supplied_session(monkeypatch):
    """A session handed in belongs to the caller's cycle: it must be reused as
    it is and left open for the next operation, not replaced or torn down."""

    class _Session:
        def __init__(self):
            self.ensure_calls = 0
            self.closed = False
            self._alive = True

        def is_alive(self):
            return self._alive

        def ensure_connected(self):
            self.ensure_calls += 1
            return True

        def execute(self, _cmd):
            return ""

        def close(self):
            self.closed = True

    def _must_not_construct(*_args, **_kwargs):
        raise AssertionError("a caller-supplied session must not be replaced with a new connection")

    monkeypatch.setattr("app.services.cisco_ssh.CiscoSSH", _must_not_construct)

    shared = _Session()
    result = get_access_points("10.0.0.10", "admin", "pass", "enable", 22, 20, shared)

    assert result == []
    assert shared.ensure_calls == 1
    assert shared.closed is False


def test_session_for_labels_a_live_shared_session_as_reused():
    from app.services.cisco_ssh import _session_for

    class _AliveSession:
        def is_alive(self):
            return True

        def ensure_connected(self):
            return True

    before = _reuse_metric_value("reused")
    session, owned = _session_for(_AliveSession(), "10.0.0.20", "admin", "pass", "enable", 22)

    assert owned is False
    assert session is not None
    assert _reuse_metric_value("reused") == before + 1


def test_session_for_labels_a_dead_shared_session_as_new_connection():
    from app.services.cisco_ssh import _session_for

    class _DeadThenReconnectedSession:
        def is_alive(self):
            return False

        def ensure_connected(self):
            return True

    before = _reuse_metric_value("new_connection")
    _session_for(_DeadThenReconnectedSession(), "10.0.0.21", "admin", "pass", "enable", 22)

    assert _reuse_metric_value("new_connection") == before + 1


def test_session_for_labels_a_failed_reconnect_as_connect_failed():
    from app.services.cisco_ssh import _session_for

    class _UnrecoverableSession:
        def is_alive(self):
            return False

        def ensure_connected(self):
            return False

    before = _reuse_metric_value("connect_failed")
    session, _owned = _session_for(_UnrecoverableSession(), "10.0.0.22", "admin", "pass", "enable", 22)

    assert session is None
    assert _reuse_metric_value("connect_failed") == before + 1


def _reuse_metric_value(outcome: str) -> float:
    from app.observability.metrics import ssh_session_reuse_total

    return ssh_session_reuse_total.labels(outcome=outcome)._value.get()


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
