from app.domains.inventory.models import NetworkSwitch
from app.services.switches.base import SwitchPollInfo
from app.services.switches.dlink_provider import DLinkSwitchProvider


def _switch() -> NetworkSwitch:
    return NetworkSwitch(name="D-Link", ip_address="172.19.17.182", vendor="dlink")


def test_dlink_uses_snmp_data_when_available(monkeypatch):
    provider = DLinkSwitchProvider()
    expected = SwitchPollInfo(is_online=True, hostname="sw-a", model_info="DGS-1210")
    monkeypatch.setattr(provider.snmp_provider, "poll_switch", lambda _switch: expected)
    monkeypatch.setattr("app.services.switches.dlink_provider._https_management_reachable", lambda _ip: False)

    assert provider.poll_switch(_switch()) is expected


def test_dlink_uses_https_liveness_when_snmp_is_unavailable(monkeypatch):
    provider = DLinkSwitchProvider()
    monkeypatch.setattr(provider.snmp_provider, "poll_switch", lambda _switch: SwitchPollInfo(is_online=False))
    monkeypatch.setattr("app.services.switches.dlink_provider._https_management_reachable", lambda _ip: True)

    info = provider.poll_switch(_switch())

    assert info.is_online is True
    assert info.model_info == "D-Link (HTTPS management; SNMP unavailable)"


def test_dlink_remains_offline_when_no_management_protocol_answers(monkeypatch):
    provider = DLinkSwitchProvider()
    monkeypatch.setattr(provider.snmp_provider, "poll_switch", lambda _switch: SwitchPollInfo(is_online=False))
    monkeypatch.setattr("app.services.switches.dlink_provider._https_management_reachable", lambda _ip: False)

    assert provider.poll_switch(_switch()).is_online is False
