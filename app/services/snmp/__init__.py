"""
SNMP service for querying printer status and toner levels.

What must be configured on each printer:
  1. SNMP v1/v2c must be ENABLED
     (Network > Protocol Settings, or Admin > Security > SNMP)
  2. Community string must be "public" (read-only) or match what you set in the app
  3. UDP port 161 must be reachable from this server — no firewall blocking it

Supported vendors (standard Printer MIB — RFC 3805):
  HP, Ricoh, Kyocera, Xerox, Canon, Lexmark, Samsung, OKI, Konica Minolta, Epson business

Additional vendor-specific fallback:
  Brother — uses proprietary OIDs when standard MIB returns no data

Printers that will NOT work:
  - Consumer inkjet printers without SNMP (Epson home, HP DeskJet basic models)
  - Very old printers (pre-2000) without Printer MIB support
"""

from .helpers import _detect_color, _detect_vendor, _is_toner_supply
from .mac import get_snmp_mac
from .oids import PrinterStatus, TonerLevel
from .poller import poll_printer, poll_printer_light

__all__ = [
    "PrinterStatus",
    "TonerLevel",
    "poll_printer",
    "poll_printer_light",
    "get_snmp_mac",
    "_detect_color",
    "_detect_vendor",
    "_is_toner_supply",
]
