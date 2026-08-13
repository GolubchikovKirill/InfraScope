from __future__ import annotations

from app.domains.inventory.models import NetworkSwitch
from app.services.switches.base import SwitchPollInfo
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


def test_prefers_ssh_offline_reason_over_snmp_when_both_fail(monkeypatch):
    """SSH's classification is specific (network_unreachable, auth_rejected,
    ...); SNMP's is not (a wrong community string and a dead route both time
    out identically over UDP). When both paths fail, the more informative
    one should win."""
    provider = CiscoSwitchProvider()

    monkeypatch.setattr(
        "app.services.switches.cisco_provider.get_switch_info",
        lambda *a, **kw: type("Info", (), {"is_online": False, "offline_reason": "network_unreachable"})(),
    )
    monkeypatch.setattr(
        provider.snmp_provider,
        "poll_switch",
        lambda _switch: SwitchPollInfo(is_online=False, offline_reason="no_response"),
    )

    result = provider.poll_switch(_build_switch())

    assert result.is_online is False
    assert result.offline_reason == "network_unreachable"


def test_falls_back_to_snmp_reason_when_ssh_gives_none(monkeypatch):
    provider = CiscoSwitchProvider()

    monkeypatch.setattr(
        "app.services.switches.cisco_provider.get_switch_info",
        lambda *a, **kw: type("Info", (), {"is_online": False, "offline_reason": None})(),
    )
    monkeypatch.setattr(
        provider.snmp_provider,
        "poll_switch",
        lambda _switch: SwitchPollInfo(is_online=False, offline_reason="no_response"),
    )

    result = provider.poll_switch(_build_switch())

    assert result.offline_reason == "no_response"


def test_ssh_success_short_circuits_snmp_entirely(monkeypatch):
    provider = CiscoSwitchProvider()

    monkeypatch.setattr(
        "app.services.switches.cisco_provider.get_switch_info",
        lambda *a, **kw: type(
            "Info",
            (),
            {"is_online": True, "hostname": "SW1", "model_info": "WS-C2960", "ios_version": "15.2", "uptime": "1d"},
        )(),
    )

    def _must_not_call(_switch):
        raise AssertionError("SNMP fallback should not run when SSH already succeeded")

    monkeypatch.setattr(provider.snmp_provider, "poll_switch", _must_not_call)

    result = provider.poll_switch(_build_switch())

    assert result.is_online is True
    assert result.offline_reason is None
