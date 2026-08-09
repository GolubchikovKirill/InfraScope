from __future__ import annotations

import logging
import ssl
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.domains.inventory.models import NetworkSwitch
from app.services.switches.base import SwitchPollInfo, SwitchPortState
from app.services.switches.snmp_provider import SnmpSwitchProvider

logger = logging.getLogger(__name__)


def _https_management_reachable(ip_address: str) -> bool:
    """Return whether the web-management endpoint answers, even with a
    self-signed certificate or an authentication challenge.

    Some installed D-Link switches expose only their HTTPS management UI:
    SNMP is intentionally disabled on them.  A successful TLS/HTTP response
    is still a reliable liveness signal; this function never authenticates
    and never changes device configuration.
    """
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    request = Request(f"https://{ip_address}/", method="HEAD")
    try:
        with urlopen(request, timeout=3, context=context):
            return True
    except HTTPError:
        # 401/403 proves the switch is reachable; credentials are not needed
        # for the availability check.
        return True
    except Exception as exc:
        logger.debug("HTTPS management probe failed for %s: %s", ip_address, exc)
        return False


class DLinkSwitchProvider:
    """SNMP-first provider for D-Link switches."""

    def __init__(self) -> None:
        self.snmp_provider = SnmpSwitchProvider()

    def poll_switch(self, switch: NetworkSwitch) -> SwitchPollInfo:
        info = self.snmp_provider.poll_switch(switch)
        if info.is_online or not _https_management_reachable(switch.ip_address):
            return info

        return SwitchPollInfo(
            is_online=True,
            hostname=switch.hostname,
            model_info=switch.model_info or "D-Link (HTTPS management; SNMP unavailable)",
            uptime=switch.uptime,
        )

    def get_ports(self, switch: NetworkSwitch) -> list[SwitchPortState]:
        return self.snmp_provider.get_ports(switch)

    def set_admin_state(self, switch: NetworkSwitch, port: str, admin_state: str) -> None:
        self.snmp_provider.set_admin_state(switch, port, admin_state)

    def set_description(self, switch: NetworkSwitch, port: str, description: str) -> None:
        self.snmp_provider.set_description(switch, port, description)

    def set_vlan(self, switch: NetworkSwitch, port: str, vlan: int) -> None:
        self.snmp_provider.set_vlan(switch, port, vlan)

    def set_mode(
        self,
        switch: NetworkSwitch,
        port: str,
        mode: str,
        access_vlan: int | None = None,
        native_vlan: int | None = None,
        allowed_vlans: str | None = None,
    ) -> None:
        self.snmp_provider.set_mode(switch, port, mode, access_vlan, native_vlan, allowed_vlans)

    def set_poe(self, switch: NetworkSwitch, port: str, action: str) -> None:
        self.snmp_provider.set_poe(switch, port, action)
