from app.models import NetworkSwitch
from app.services.switches.cisco_provider import CiscoSwitchProvider
from app.services.switches.dlink_provider import DLinkSwitchProvider
from app.services.switches.resolver import resolve_switch_provider
from app.services.switches.snmp_provider import SnmpSwitchProvider


def _switch(vendor: str) -> NetworkSwitch:
    return NetworkSwitch(name="sw", ip_address="10.0.0.1", vendor=vendor)


def test_resolver_returns_cisco_provider():
    provider = resolve_switch_provider(_switch("cisco"))
    assert isinstance(provider, CiscoSwitchProvider)


def test_resolver_returns_dlink_provider():
    provider = resolve_switch_provider(_switch("dlink"))
    assert isinstance(provider, DLinkSwitchProvider)


def test_resolver_returns_generic_snmp_for_unknown_vendor():
    provider = resolve_switch_provider(_switch("unknown"))
    assert isinstance(provider, SnmpSwitchProvider)
