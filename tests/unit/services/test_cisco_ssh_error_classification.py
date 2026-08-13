from __future__ import annotations

import socket

import paramiko
import pytest

from app.services.cisco_ssh import CiscoSSH, _classify_ssh_error, get_switch_info


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (paramiko.AuthenticationException("bad creds"), "auth_rejected"),
        (paramiko.BadAuthenticationType("nope", ["password"]), "auth_rejected"),
        (socket.gaierror("name resolution failed"), "dns_failure"),
        (socket.timeout("timed out"), "timeout"),
        (TimeoutError("timed out"), "timeout"),
        (ConnectionRefusedError("refused"), "connection_refused"),
        (OSError("No route to host"), "network_unreachable"),
        (paramiko.SSHException("protocol error"), "protocol_error"),
        (ValueError("something else entirely"), "other"),
    ],
)
def test_classify_ssh_error(exc, expected):
    assert _classify_ssh_error(exc) == expected


def test_classify_prefers_auth_over_broader_sshexception():
    """AuthenticationException IS an SSHException - order must not let the
    broader check swallow it and report a vague protocol_error instead of
    the actionable auth_rejected."""
    assert _classify_ssh_error(paramiko.AuthenticationException("nope")) == "auth_rejected"


def test_connect_reports_network_unreachable_not_auth_failed(monkeypatch):
    """The exact regression this exists to prevent: a connection that never
    reaches the SSH protocol at all (route down, port filtered) must not be
    reported as a rejected password. Mocks paramiko's own connect() - one
    level below _connect_password - so the real classification logic inside
    _connect_password runs, not a stand-in for it."""
    ssh = CiscoSSH("10.0.0.50", "admin", "pass")
    monkeypatch.setattr(CiscoSSH, "_query_auth_methods", lambda _self: ["password"])
    monkeypatch.setattr(paramiko.SSHClient, "connect", lambda *a, **kw: (_ for _ in ()).throw(OSError("No route to host")))

    assert ssh.connect() is False
    assert ssh.last_failure_reason == "network_unreachable"


def test_connect_reports_auth_rejected_for_a_real_bad_password(monkeypatch):
    ssh = CiscoSSH("10.0.0.51", "admin", "wrong-password")
    monkeypatch.setattr(CiscoSSH, "_query_auth_methods", lambda _self: ["password"])

    def _reject_connect(*_a, **_kw):
        raise paramiko.AuthenticationException("Authentication failed")

    monkeypatch.setattr(paramiko.SSHClient, "connect", _reject_connect)

    assert ssh.connect() is False
    assert ssh.last_failure_reason == "auth_rejected"


def test_get_switch_info_surfaces_offline_reason(monkeypatch):
    def _unreachable(self):
        self.last_failure_reason = "network_unreachable"
        return False

    monkeypatch.setattr(CiscoSSH, "connect", _unreachable)

    info = get_switch_info("10.0.0.52", "admin", "pass")

    assert info.is_online is False
    assert info.offline_reason == "network_unreachable"
