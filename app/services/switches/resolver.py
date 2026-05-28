from __future__ import annotations

from app.domains.inventory.models import NetworkSwitch
from app.services.switches.cisco_provider import CiscoSwitchProvider
from app.services.switches.dlink_provider import DLinkSwitchProvider
from app.services.switches.snmp_provider import SnmpSwitchProvider

_CISCO = CiscoSwitchProvider()
_DLINK = DLinkSwitchProvider()
_GENERIC = SnmpSwitchProvider()


def resolve_switch_provider(switch: NetworkSwitch):
    vendor = (switch.vendor or "generic").lower()
    if vendor == "cisco":
        return _CISCO
    if vendor == "dlink":
        return _DLINK
    return _GENERIC
