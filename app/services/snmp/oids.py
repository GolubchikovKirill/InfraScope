from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── MIB-2 System OIDs ──────────────────────────────────────────────────────
OID_SYS_DESCR = "1.3.6.1.2.1.1.1.0"
OID_SYS_NAME = "1.3.6.1.2.1.1.5.0"

# ── Host Resources MIB — printer status (walk to find any hrDeviceIndex) ───
OID_PRINTER_STATUS_BASE = "1.3.6.1.2.1.25.3.5.1.1"

# ── Printer MIB (RFC 3805) — marker supply OIDs ────────────────────────────
# Walk from base WITHOUT device index so we catch all hrDeviceIndex values.
# Some printers use index 1, others use 2 — walking the base handles both.
OID_MARKER_DESCR = "1.3.6.1.2.1.43.11.1.1.6"  # prtMarkerSuppliesDescription
OID_MARKER_TYPE = "1.3.6.1.2.1.43.11.1.1.5"  # prtMarkerSuppliesType
OID_MARKER_MAX = "1.3.6.1.2.1.43.11.1.1.8"  # prtMarkerSuppliesMaxCapacity
OID_MARKER_LEVEL = "1.3.6.1.2.1.43.11.1.1.9"  # prtMarkerSuppliesLevel
OID_MARKER_COLORANT_IDX = "1.3.6.1.2.1.43.11.1.1.3"  # prtMarkerSuppliesColorantIndex
OID_COLORANT_VALUE = "1.3.6.1.2.1.43.12.1.1.4"  # prtMarkerColorantValue

# RFC 3805 prtMarkerSuppliesType values — consumable types we track
_CONSUMABLE_SUPPLY_TYPES: frozenset[int] = frozenset(
    {
        3,  # toner
        5,  # ink
        6,  # inkCartridge
        10,  # developer
        21,  # tonerCartridge
    }
)
# Non-consumable supply types we always skip
_NON_CONSUMABLE_SUPPLY_TYPES: frozenset[int] = frozenset(
    {
        4,  # wasteToner
        8,  # wasteInk
        9,  # opc (photo conductor)
        11,  # fuserOil
        14,  # wasteWax
        15,  # fuser
        16,  # coronaWire
        17,  # fuserOilWick
        18,  # cleanerUnit
        19,  # fuserCleaningPad
        20,  # transferUnit
    }
)

# ── Brother proprietary OIDs ────────────────────────────────────────────────
BROTHER_TONER_BASE = "1.3.6.1.4.1.2435.2.3.9.4.2.1.5.5.10.0.1"
BROTHER_COLOR_MAP: dict[str, str] = {
    "1": "black",
    "2": "cyan",
    "3": "magenta",
    "4": "yellow",
}

# ── Ricoh proprietary OIDs ─────────────────────────────────────────────────
# Ricoh private MIB: more precise toner levels than standard MIB on some models
RICOH_SUPPLY_LEVEL = "1.3.6.1.4.1.367.3.2.1.2.24.1.1.5"  # remaining level (%)
RICOH_SUPPLY_DESCR = "1.3.6.1.4.1.367.3.2.1.2.24.1.1.3"  # supply description

PRINTER_STATUS_MAP: dict[int, str] = {
    1: "other",
    2: "unknown",
    3: "idle",
    4: "printing",
    5: "warmup",
}

# Supply description keywords → canonical color name.
# Padded with spaces so " bk " matches as a word, not substring of "black".
COLOR_KEYWORDS: dict[str, str] = {
    # English
    "black": "black",
    "cyan": "cyan",
    "magenta": "magenta",
    "yellow": "yellow",
    "photo black": "black",
    "matte black": "black",
    # Abbreviations (space-padded for word boundary)
    " bk ": "black",
    "-bk ": "black",
    " bk\n": "black",
    " k ": "black",
    " c ": "cyan",
    " m ": "magenta",
    " y ": "yellow",
    # German
    "schwarz": "black",
    "gelb": "yellow",
    # French
    "noir": "black",
    "jaune": "yellow",
    # Russian
    "чёрный": "black",
    "черный": "black",
    "голубой": "cyan",
    "пурпурный": "magenta",
    "малиновый": "magenta",
    "жёлтый": "yellow",
    "желтый": "yellow",
}

# Words that indicate a supply is NOT toner (drum, maintenance, waste, etc.)
NON_TONER_KEYWORDS: frozenset[str] = frozenset(
    {
        "drum",
        "kit",
        "maintenance",
        "fuser",
        "waste",
        "belt",
        "transfer",
        "roller",
        "cleaner",
        "filter",
    }
)

SNMP_TIMEOUT = 5
SNMP_RETRIES = 2


@dataclass
class TonerLevel:
    description: str
    color: str | None
    level_pct: int | None
    max_capacity: int
    current_level: int


@dataclass
class PrinterStatus:
    is_online: bool
    status: str
    toners: list[TonerLevel] = field(default_factory=list)
    toner_black: int | None = None
    toner_cyan: int | None = None
    toner_magenta: int | None = None
    toner_yellow: int | None = None
    sys_description: str | None = None
    vendor: str | None = None


# Regex patterns for cartridge model numbers ending with a color code.
# Matches: TK-5240K, TN-247BK, W2210A (HP doesn't use this pattern, but others do)
# The letter must follow a digit to avoid false positives.
_SUFFIX_COLOR_RE: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\d+bk\b", re.IGNORECASE), "black"),
    (re.compile(r"\d+k\b", re.IGNORECASE), "black"),
    (re.compile(r"\d+c\b", re.IGNORECASE), "cyan"),
    (re.compile(r"\d+m\b", re.IGNORECASE), "magenta"),
    (re.compile(r"\d+y\b", re.IGNORECASE), "yellow"),
]
