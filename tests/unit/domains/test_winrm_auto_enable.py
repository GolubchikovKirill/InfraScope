import base64
import re
import socket

import pytest

from app.core.config import settings
from app.domains.remote_access import winrm_bootstrap as bootstrap


def test_existing_listener_is_never_reconfigured(monkeypatch):
    monkeypatch.setattr(settings, "WINRM_AUTO_ENABLE", True)
    monkeypatch.setattr(bootstrap, "resolve_hostname", lambda *a, **kw: "10.0.0.1")
    monkeypatch.setattr(bootstrap, "_listening", lambda _address: True)
    monkeypatch.setattr(bootstrap, "_start_bootstrap", lambda *a: pytest.fail("unexpected change"))
    bootstrap.ensure_winrm("host")


def test_refused_listener_is_prepared_and_rechecked(monkeypatch):
    monkeypatch.setattr(settings, "WINRM_AUTO_ENABLE", True)
    monkeypatch.setattr(settings, "ALLOW_HARDWARE_WRITES", None)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "WINRM_USE_SSL", False)
    monkeypatch.setattr(settings, "WINRM_PORT", 5985)
    monkeypatch.setattr(settings, "WINRM_ADMIN_USERNAME", "DOMAIN\\svc")
    monkeypatch.setattr(bootstrap, "resolve_hostname", lambda *a, **kw: "10.0.0.1")
    checks = iter([False, True])
    monkeypatch.setattr(bootstrap, "_listening", lambda _address: next(checks))
    calls = []
    monkeypatch.setattr(bootstrap, "_start_bootstrap", lambda *args: calls.append(args))
    bootstrap.ensure_winrm("host")
    assert calls[0][:3] == ("10.0.0.1", "svc", "DOMAIN")
    script = base64.b64decode(calls[0][3].rsplit(" ", 1)[1]).decode("utf-16-le")
    assert "finally" in script and "RemoteAddresses" in script


def test_system_task_has_unique_name_cleanup_and_no_schtasks_length_limit():
    encoded = base64.b64encode("Write-Output 'test'".encode("utf-16-le")).decode()
    command = bootstrap._scheduled_command("powershell.exe -EncodedCommand " + encoded)
    script = base64.b64decode(command.rsplit(" ", 1)[1]).decode("utf-16-le")
    assert "Principal.UserId='SYSTEM'" in script
    assert "RegisterTaskDefinition" in script and "schtasks" not in script
    action_args = re.search(r"\$a.Arguments='([^']+)'", script).group(1)
    action = base64.b64decode(action_args.rsplit(" ", 1)[1]).decode("utf-16-le")
    assert "Write-Output 'test'" in action
    assert "finally" in action and "DeleteTask('InfraScope-WinRM-" in action
    assert len(command) < 8191


def test_network_timeout_does_not_launch_wmi(monkeypatch):
    monkeypatch.setattr(settings, "WINRM_AUTO_ENABLE", True)
    monkeypatch.setattr(bootstrap, "resolve_hostname", lambda *a, **kw: "10.0.0.1")
    def timeout(*_args, **_kwargs):
        raise TimeoutError()
    monkeypatch.setattr(bootstrap.socket, "create_connection", timeout)
    monkeypatch.setattr(bootstrap, "_start_bootstrap", lambda *a: pytest.fail("unexpected change"))
    with pytest.raises(socket.timeout):
        bootstrap.ensure_winrm("host")
