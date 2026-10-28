"""SSH access to Cisco IOS switches.

  - switch info (hostname, model, IOS version, uptime)
  - access points on a VLAN via CDP, enriched from the MAC table, PoE and ARP
  - camera ports by VLAN
  - AP / camera reboots by port shutdown or PoE power cycling

Layout: `session` is one interactive SSH session (`CiscoSSH`), `client` the
operations on a switch (`CiscoSwitchClient` plus the function API the callers
use), `parsers` turn IOS output into the records in `models`, and `compat`
re-enables the legacy SSH algorithms old IOS images need - applied on import.
"""

from . import compat as _compat  # noqa: F401  (installs legacy kex + log filter)
from .client import (
    CiscoSwitchClient,
    get_access_points,
    get_camera_ports,
    get_port_poe_power,
    get_switch_arp_mac_map,
    get_switch_info,
    poe_cycle_ap,
    poe_cycle_ports_bulk,
    reboot_ap,
)
from .compat import _KexGroup1SHA1, _KexGroup14SHA1, _QuietIncompatiblePeer
from .models import APInfo, CameraPortInfo, InterfaceStatusRow, SwitchInfo
from .parsers import (
    _enrich_arp,
    _enrich_camera_poe,
    _enrich_mac_from_table,
    _enrich_poe,
    _format_mac,
    _mac_from_ap_name,
    _normalize_port,
    _parse_arp_mac_to_ip,
    _parse_cdp_access_points,
    _parse_ports_on_vlans,
    parse_interface_status_table,
    parse_port_poe_watts,
    parse_show_version,
)
from .session import (
    _AUTH_METHOD_CACHE,
    CMD_TIMEOUT,
    SSH_TIMEOUT,
    CiscoSSH,
    _classify_ssh_error,
    _session_for,
)

__all__ = [
    "APInfo",
    "CMD_TIMEOUT",
    "CameraPortInfo",
    "CiscoSSH",
    "CiscoSwitchClient",
    "InterfaceStatusRow",
    "SSH_TIMEOUT",
    "SwitchInfo",
    "_AUTH_METHOD_CACHE",
    "_KexGroup14SHA1",
    "_KexGroup1SHA1",
    "_QuietIncompatiblePeer",
    "_classify_ssh_error",
    "_enrich_arp",
    "_enrich_camera_poe",
    "_enrich_mac_from_table",
    "_enrich_poe",
    "_format_mac",
    "_mac_from_ap_name",
    "_normalize_port",
    "_parse_arp_mac_to_ip",
    "_parse_cdp_access_points",
    "_parse_ports_on_vlans",
    "_session_for",
    "get_access_points",
    "get_camera_ports",
    "get_port_poe_power",
    "get_switch_arp_mac_map",
    "get_switch_info",
    "parse_interface_status_table",
    "parse_port_poe_watts",
    "parse_show_version",
    "poe_cycle_ap",
    "poe_cycle_ports_bulk",
    "reboot_ap",
]
