from __future__ import annotations

import logging
import re

from .oids import (
    _CONSUMABLE_SUPPLY_TYPES,
    _NON_CONSUMABLE_SUPPLY_TYPES,
    _SUFFIX_COLOR_RE,
    COLOR_KEYWORDS,
    NON_TONER_KEYWORDS,
)

logger = logging.getLogger(__name__)


def _detect_color(description: str) -> str | None:
    desc = " " + description.lower() + " "
    for keyword, color in COLOR_KEYWORDS.items():
        if keyword in desc:
            return color
    for pattern, color in _SUFFIX_COLOR_RE:
        if pattern.search(description):
            return color
    return None


def _is_toner_supply(description: str, supply_type: int | None) -> bool:
    """Return True if the supply is toner/ink, not a drum or maintenance kit."""
    desc_lower = description.lower()
    if any(kw in desc_lower for kw in NON_TONER_KEYWORDS):
        return False
    if supply_type is not None and supply_type != 0:
        if supply_type in _NON_CONSUMABLE_SUPPLY_TYPES:
            return False
        if supply_type in _CONSUMABLE_SUPPLY_TYPES:
            return True
        # Unknown type (1=other, 2=unknown, etc.) — accept if description
        # doesn't look like a non-consumable
        return True
    return True


def _detect_vendor(sys_descr: str) -> str | None:
    d = sys_descr.lower()
    if "brother" in d:
        return "brother"
    if "hewlett" in d or re.search(r"\bhp\b", d) or "laserjet" in d or "officejet" in d:
        return "hp"
    if "ricoh" in d or "aficio" in d or "savin" in d or "gestetner" in d or "lanier" in d:
        return "ricoh"
    if "kyocera" in d or "mita" in d:
        return "kyocera"
    if "canon" in d:
        return "canon"
    if "xerox" in d:
        return "xerox"
    if "lexmark" in d:
        return "lexmark"
    if "epson" in d:
        return "epson"
    if "samsung" in d:
        return "samsung"
    if "oki" in d or "okidata" in d:
        return "oki"
    if "konica" in d or "minolta" in d or "bizhub" in d:
        return "konica"
    return None


def _extract_supply_key(oid: str) -> str:
    """Extract the last two OID segments as a correlation key.

    Example: '1.3.6.1.2.1.43.11.1.1.6.1.3' → '1.3'
             hrDeviceIndex=1, supplyIndex=3
    This lets us correctly match description/type/max/level rows
    even when a printer has multiple device instances.
    """
    parts = oid.rsplit(".", 2)
    return f"{parts[-2]}.{parts[-1]}" if len(parts) >= 3 else parts[-1]
