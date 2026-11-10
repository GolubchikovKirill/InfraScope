import pytest

from app.core.config import settings
from app.domains.remote_access import winrm_exec


@pytest.mark.parametrize(("ssl", "transport", "expected"), [
    (False, "ntlm", "http://10.10.98.146:5985/wsman"),
    (True, "ntlm", "https://VNA-TV-1101:5985/wsman"),
    (False, "kerberos", "http://VNA-TV-1101:5985/wsman"),
])
def test_winrm_resolves_short_names_without_breaking_tls_or_kerberos(monkeypatch, ssl, transport, expected):
    monkeypatch.setattr(settings, "WINRM_ADMIN_USERNAME", "test-account")
    monkeypatch.setattr(settings, "WINRM_ADMIN_PASSWORD", "test-only")
    monkeypatch.setattr(settings, "WINRM_USE_SSL", ssl)
    monkeypatch.setattr(settings, "WINRM_TRANSPORT", transport)
    monkeypatch.setattr(settings, "WINRM_PORT", 5985)
    calls = []

    def resolve(*_a, **_kw):
        calls.append(True)
        return "10.10.98.146"

    monkeypatch.setattr(winrm_exec, "resolve_hostname", resolve)
    monkeypatch.setattr(winrm_exec.winrm, "Session", lambda endpoint, **_kw: endpoint)
    assert winrm_exec._session("VNA-TV-1101") == expected
    assert bool(calls) == (not ssl and transport == "ntlm")
