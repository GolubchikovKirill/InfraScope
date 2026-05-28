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

from __future__ import annotations

import asyncio
import http.client
import logging
import re
import socket
import ssl as _ssl
import urllib.error
import urllib.request
import warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from app.observability.metrics import snmp_operations_total

warnings.filterwarnings("ignore", message=".*pysnmp-lextudio.*")

from pysnmp.hlapi.asyncio import (  # noqa: E402
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
)
from pysnmp.hlapi.asyncio.cmdgen import getCmd, walkCmd  # noqa: E402

logger = logging.getLogger(__name__)

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

# ── Helpers ────────────────────────────────────────────────────────────────


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


# ── SNMP primitives ────────────────────────────────────────────────────────


def _decode_snmp_value(val) -> str:
    """Decode SNMP value, handling UTF-8 encoded OctetStrings correctly."""
    if hasattr(val, "asOctets"):
        raw = val.asOctets()
        try:
            return raw.decode("utf-8")
        except (UnicodeDecodeError, ValueError):
            pass
        try:
            return raw.decode("latin-1")
        except (UnicodeDecodeError, ValueError):
            pass
    return str(val)


async def _snmp_get(
    engine: SnmpEngine,
    target: UdpTransportTarget,
    community: CommunityData,
    oid: str,
) -> str | None:
    error_indication, error_status, _error_index, var_binds = await getCmd(
        engine,
        community,
        target,
        ContextData(),
        ObjectType(ObjectIdentity(oid)),
    )
    if error_indication or error_status:
        return None
    for _oid, val in var_binds:
        return _decode_snmp_value(val)
    return None


async def _snmp_walk(
    engine: SnmpEngine,
    target: UdpTransportTarget,
    community: CommunityData,
    oid: str,
) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    async for error_indication, error_status, _error_index, var_binds in walkCmd(
        engine,
        community,
        target,
        ContextData(),
        ObjectType(ObjectIdentity(oid)),
        lexicographicMode=False,
    ):
        if error_indication or error_status:
            break
        for oid_result, val in var_binds:
            results.append((str(oid_result), _decode_snmp_value(val)))
    return results


# ── Toner strategies ───────────────────────────────────────────────────────


async def _get_standard_toners(
    engine: SnmpEngine,
    target: UdpTransportTarget,
    comm: CommunityData,
) -> list[TonerLevel]:
    """Standard Printer MIB (RFC 3805). Works on HP, Ricoh, Kyocera, Canon, Xerox, etc."""
    descriptions = await _snmp_walk(engine, target, comm, OID_MARKER_DESCR)

    # Fallback: if WALK returned nothing, try direct GETs on common indices.
    # Some HP printers block WALK but respond to individual GETs.
    if not descriptions:
        for dev_idx in (1, 2):
            for sup_idx in range(1, 9):
                oid = f"{OID_MARKER_DESCR}.{dev_idx}.{sup_idx}"
                val = await _snmp_get(engine, target, comm, oid)
                if val and val.strip():
                    descriptions.append((oid, val))
            if descriptions:
                break

    if not descriptions:
        return []

    types_raw = await _snmp_walk(engine, target, comm, OID_MARKER_TYPE)
    max_raw = await _snmp_walk(engine, target, comm, OID_MARKER_MAX)
    level_raw = await _snmp_walk(engine, target, comm, OID_MARKER_LEVEL)

    # If WALK worked for descriptions but not for levels, try GET fallback too
    if descriptions and not level_raw:
        for oid_d, _ in descriptions:
            key = _extract_supply_key(oid_d)
            level_oid = f"{OID_MARKER_LEVEL}.{key}"
            max_oid = f"{OID_MARKER_MAX}.{key}"
            type_oid = f"{OID_MARKER_TYPE}.{key}"
            lv = await _snmp_get(engine, target, comm, level_oid)
            if lv is not None:
                level_raw.append((level_oid, lv))
            mv = await _snmp_get(engine, target, comm, max_oid)
            if mv is not None:
                max_raw.append((max_oid, mv))
            tv = await _snmp_get(engine, target, comm, type_oid)
            if tv is not None:
                types_raw.append((type_oid, tv))

    # Colorant-based color detection (Ricoh, some Canon/Xerox):
    # prtMarkerSuppliesColorantIndex links supply → colorant index
    # prtMarkerColorantValue gives the actual color name ("black", "cyan", etc.)
    colorant_idx_raw = await _snmp_walk(engine, target, comm, OID_MARKER_COLORANT_IDX)
    colorant_val_raw = await _snmp_walk(engine, target, comm, OID_COLORANT_VALUE)

    types_map = {_extract_supply_key(oid): val for oid, val in types_raw}
    max_map = {_extract_supply_key(oid): val for oid, val in max_raw}
    level_map = {_extract_supply_key(oid): val for oid, val in level_raw}
    colorant_idx_map = {_extract_supply_key(oid): val for oid, val in colorant_idx_raw}

    # Build colorant index → color name lookup
    # OID: .43.12.1.1.4.{deviceIdx}.{colorantIdx} → value is color name
    colorant_by_idx: dict[str, str] = {}
    for oid_c, color_name in colorant_val_raw:
        parts = oid_c.rsplit(".", 2)
        if len(parts) >= 3:
            device_idx = parts[-2]
            colorant_idx = parts[-1]
            colorant_by_idx[f"{device_idx}.{colorant_idx}"] = color_name.lower().strip()

    toners: list[TonerLevel] = []
    for oid_d, desc in descriptions:
        key = _extract_supply_key(oid_d)
        device_idx = key.split(".")[0] if "." in key else "1"

        supply_type: int | None = None
        try:
            supply_type = int(types_map[key]) if key in types_map else None
        except (ValueError, TypeError):
            pass

        if not _is_toner_supply(desc, supply_type):
            logger.debug("Skipping non-toner supply: %r (type=%s)", desc, supply_type)
            continue

        try:
            max_val = int(max_map.get(key, 0))
        except (ValueError, TypeError):
            max_val = 0

        try:
            cur_val = int(level_map.get(key, 0))
        except (ValueError, TypeError):
            cur_val = 0

        if cur_val == -3:
            pct = -3
        elif cur_val < 0:
            pct = -2
        elif max_val > 0:
            pct = max(0, min(100, round(cur_val / max_val * 100)))
        else:
            pct = None

        # Color detection: try description first, then colorant OID
        color = _detect_color(desc)
        if not color:
            ci = colorant_idx_map.get(key)
            if ci:
                colorant_key = f"{device_idx}.{ci}"
                colorant_color = colorant_by_idx.get(colorant_key, "")
                if colorant_color:
                    color = _detect_color(colorant_color)
                    if not color and colorant_color in ("black", "cyan", "magenta", "yellow"):
                        color = colorant_color
        if not color and len(descriptions) == 1:
            # Monochrome printer with single supply — assume black
            color = "black"

        toners.append(
            TonerLevel(
                description=desc,
                color=color,
                level_pct=pct,
                max_capacity=max_val,
                current_level=cur_val,
            )
        )

    if descriptions and not toners:
        logger.info(
            "Found %d supply entries but all filtered out — descriptions: %s",
            len(descriptions),
            [(d, types_map.get(_extract_supply_key(o))) for o, d in descriptions],
        )

    return toners


async def _get_brother_toners(
    engine: SnmpEngine,
    target: UdpTransportTarget,
    comm: CommunityData,
) -> list[TonerLevel]:
    """Brother proprietary toner OIDs. Returns percentage directly (0-100)."""
    raw = await _snmp_walk(engine, target, comm, BROTHER_TONER_BASE)
    if not raw:
        return []

    toners: list[TonerLevel] = []
    for oid, val in raw:
        color_idx = oid.rsplit(".", 1)[-1]
        color = BROTHER_COLOR_MAP.get(color_idx)
        try:
            pct = max(0, min(100, int(val)))
        except (ValueError, TypeError):
            pct = None

        toners.append(
            TonerLevel(
                description=f"{color or 'unknown'} toner",
                color=color,
                level_pct=pct,
                max_capacity=100,
                current_level=pct if pct is not None else 0,
            )
        )
    return toners


async def _get_ricoh_toners(
    engine: SnmpEngine,
    target: UdpTransportTarget,
    comm: CommunityData,
    standard_toners: list[TonerLevel],
) -> list[TonerLevel]:
    """Try Ricoh proprietary OIDs to get precise levels when standard MIB returns -3."""
    level_raw = await _snmp_walk(engine, target, comm, RICOH_SUPPLY_LEVEL)
    if not level_raw:
        return standard_toners

    descr_raw = await _snmp_walk(engine, target, comm, RICOH_SUPPLY_DESCR)
    descr_map = {oid.rsplit(".", 1)[-1]: val for oid, val in descr_raw}

    ricoh_toners: list[TonerLevel] = []
    for oid, val in level_raw:
        idx = oid.rsplit(".", 1)[-1]
        desc = descr_map.get(idx, "")
        try:
            raw_val = int(val)
        except (ValueError, TypeError):
            continue

        # Ricoh private MIB also uses -3 = "some remaining"
        if raw_val == -3:
            pct = -3
        elif raw_val < 0:
            pct = -2
        else:
            pct = max(0, min(100, raw_val))

        color = _detect_color(desc)
        if not color and len(level_raw) == 1:
            color = "black"

        ricoh_toners.append(
            TonerLevel(
                description=desc or f"{color or 'unknown'} toner",
                color=color,
                level_pct=pct,
                max_capacity=100,
                current_level=raw_val if raw_val >= 0 else 0,
            )
        )

    # Only use Ricoh proprietary data if it has at least one precise level (>= 0)
    has_precise = any(t.level_pct is not None and t.level_pct >= 0 for t in ricoh_toners)
    if ricoh_toners and has_precise:
        logger.info(
            "Ricoh proprietary OIDs returned %d toner(s) with precise levels",
            len(ricoh_toners),
        )
        return ricoh_toners
    return standard_toners


# ── HTTP-based toner scraping (for printers with SNMP disabled) ────────────

_HTTP_TIMEOUT = 8

# HP EWS endpoints (ordered by reliability)
_HP_URLS = [
    "/DevMgmt/ConsumableConfigDyn.xml",
    "/info_suppliesStatus.html",
]

_SSL_CTX = _ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = _ssl.CERT_NONE


def _http_get(ip: str, path: str, timeout: float = _HTTP_TIMEOUT) -> bytes | None:
    for scheme in ("http", "https"):
        url = f"{scheme}://{ip}{path}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "InfraScope/1.0"})
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
                # Read in chunks to handle printers that close connection early
                chunks = []
                try:
                    while True:
                        chunk = resp.read(4096)
                        if not chunk:
                            break
                        chunks.append(chunk)
                except http.client.IncompleteRead as e:
                    if e.partial:
                        chunks.append(e.partial)
                data = b"".join(chunks)
                if data:
                    logger.info("HTTP %s => %d bytes", url, len(data))
                    return data
        except http.client.IncompleteRead as e:
            if e.partial and len(e.partial) > 500:
                logger.info("HTTP %s => IncompleteRead, using %d partial bytes", url, len(e.partial))
                return e.partial
            logger.warning("HTTP %s => IncompleteRead, only %d bytes", url, len(e.partial) if e.partial else 0)
            continue
        except urllib.error.HTTPError as e:
            logger.info("HTTP %s => %d %s", url, e.code, e.reason)
            if scheme == "http" and e.code in (301, 302, 308):
                continue
            break
        except urllib.error.URLError as e:
            reason = str(e.reason)
            if "Connection refused" in reason:
                continue
            logger.warning("HTTP %s => URLError: %s", url, reason)
            continue
        except Exception as e:
            logger.warning("HTTP %s => %s: %s", url, type(e).__name__, e)
            continue
    return None


def _parse_hp_consumable_xml(data: bytes) -> list[TonerLevel]:
    """Parse HP EWS ConsumableConfigDyn.xml for toner levels."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return []

    toners: list[TonerLevel] = []

    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag != "ConsumableInfo":
            continue

        color = None
        pct = None
        desc = ""
        is_consumable = False

        for child in elem.iter():
            ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            text = (child.text or "").strip()
            if not text:
                continue

            if ctag == "ConsumableLabelCode":
                lc = text.lower()
                if lc in ("black", "cyan", "magenta", "yellow"):
                    color = lc
                    is_consumable = True
                elif "black" in lc:
                    color = "black"
                    is_consumable = True
            elif ctag == "MarkerColor":
                if not color:
                    mc = text.lower()
                    for c in ("black", "cyan", "magenta", "yellow"):
                        if c in mc:
                            color = c
                            is_consumable = True
                            break
            elif ctag == "ConsumablePercentageLevelRemaining":
                try:
                    pct = max(0, min(100, int(text)))
                except (ValueError, TypeError):
                    pass
            elif ctag in ("ConsumableTypeEnum", "ConsumableType"):
                t = text.lower()
                if "ink" in t or "toner" in t or "colorant" in t or "printcolorant" in t:
                    is_consumable = True
            elif ctag == "ProductNumber":
                desc = text

        if is_consumable and pct is not None and color:
            toners.append(
                TonerLevel(
                    description=desc or f"{color} toner",
                    color=color,
                    level_pct=pct,
                    max_capacity=100,
                    current_level=pct,
                )
            )

    return toners


# Regex: color from GIF filename, then percentage in next <td>
_HP_HTML_TONER_RE = re.compile(
    r'<img\s+src="(Black|Cyan|Magenta|Yellow)_Toner\.gif"'
    r".*?"
    r"(\d+)\s*%",
    re.IGNORECASE | re.DOTALL,
)

# Fallback: any percentage near a color keyword in the HTML
_HP_HTML_COLOR_PCT_RE = re.compile(
    r"(?:"
    r"(?P<color1>black|cyan|magenta|yellow|"
    r"[чЧ]ерн\w*|[гГ]олуб\w*|[пП]урпурн\w*|[мМ]алинов\w*|[жЖ]елт\w*)"
    r".{1,300}?(?P<pct1>\d{1,3})\s*%"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_HTML_COLOR_MAP: dict[str, str] = {
    "black": "black",
    "cyan": "cyan",
    "magenta": "magenta",
    "yellow": "yellow",
    "черн": "black",
    "голуб": "cyan",
    "пурпурн": "magenta",
    "малинов": "magenta",
    "желт": "yellow",
}


def _parse_hp_supplies_html(data: bytes) -> list[TonerLevel]:
    """Parse older HP EWS /info_suppliesStatus.html for toner levels."""
    text = data.decode("utf-8", errors="replace")
    toners: list[TonerLevel] = []
    seen_colors: set[str] = set()

    # Primary: match GIF image pattern (most reliable)
    for m in _HP_HTML_TONER_RE.finditer(text):
        color = m.group(1).lower()
        pct = int(m.group(2))
        if color not in seen_colors:
            seen_colors.add(color)
            toners.append(
                TonerLevel(
                    description=f"{color} cartridge",
                    color=color,
                    level_pct=max(0, min(100, pct)),
                    max_capacity=100,
                    current_level=max(0, min(100, pct)),
                )
            )

    if toners:
        return toners

    # Fallback: regex for color keyword near percentage
    for m in _HP_HTML_COLOR_PCT_RE.finditer(text):
        raw_color = m.group("color1").lower()
        pct = int(m.group("pct1"))
        if pct > 100:
            continue
        color = None
        for prefix, canonical in _HTML_COLOR_MAP.items():
            if raw_color.startswith(prefix):
                color = canonical
                break
        if color and color not in seen_colors:
            seen_colors.add(color)
            toners.append(
                TonerLevel(
                    description=f"{color} cartridge",
                    color=color,
                    level_pct=pct,
                    max_capacity=100,
                    current_level=pct,
                )
            )

    return toners


def _get_toners_via_http(ip: str) -> list[TonerLevel]:
    """Try to scrape toner data from printer's web interface (HP EWS, etc.)."""
    for path in _HP_URLS:
        data = _http_get(ip, path)
        if not data:
            logger.info("%s: HTTP %s returned no data", ip, path)
            continue

        # Try XML parser first (newer HP models)
        if b"<" in data[:100] and (b"ConsumableInfo" in data or b"consumable" in data.lower()):
            toners = _parse_hp_consumable_xml(data)
            if toners:
                logger.info("%s: got %d toner(s) via HTTP XML (%s)", ip, len(toners), path)
                return toners

        # Try HTML parser (older HP models like CM2320, CP1525, CP2025)
        if b"Toner.gif" in data or b"toner" in data.lower() or b"cartridge" in data.lower():
            toners = _parse_hp_supplies_html(data)
            if toners:
                logger.info("%s: got %d toner(s) via HTTP HTML (%s)", ip, len(toners), path)
                return toners

    return []


# ── TCP fallback ───────────────────────────────────────────────────────────

_TCP_FALLBACK_PORTS = (80, 443, 9100, 631)
_TCP_TIMEOUT = 2.0


def _tcp_port_open(ip: str, port: int, timeout: float = _TCP_TIMEOUT) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except (OSError, TimeoutError):
        return False


def _tcp_reachable(ip: str) -> bool:
    """Check if any common printer port is open (HTTP, HTTPS, JetDirect, IPP)."""
    for port in _TCP_FALLBACK_PORTS:
        if _tcp_port_open(ip, port):
            return True
    return False


# ── Main poller ────────────────────────────────────────────────────────────


async def _poll_printer_async(ip_address: str, community: str = "public") -> PrinterStatus:
    engine = SnmpEngine()
    try:
        target = UdpTransportTarget((ip_address, 161), timeout=SNMP_TIMEOUT, retries=SNMP_RETRIES)
    except Exception as e:
        logger.debug("Cannot create SNMP target for %s: %s", ip_address, e)
        return PrinterStatus(is_online=False, status="unreachable")

    comm = CommunityData(community)

    sys_descr = await _snmp_get(engine, target, comm, OID_SYS_DESCR)
    if sys_descr is None:
        # SNMP failed — try TCP ports as fallback before marking offline
        reachable = await asyncio.to_thread(_tcp_reachable, ip_address)
        if not reachable:
            logger.debug("%s: no SNMP response and no open TCP ports", ip_address)
            return PrinterStatus(is_online=False, status="offline")

        # TCP port open — try to get toner data via HTTP
        http_toners = await asyncio.to_thread(_get_toners_via_http, ip_address)
        result = PrinterStatus(
            is_online=True,
            status="online (HTTP)" if http_toners else "online (no SNMP)",
            toners=http_toners,
            sys_description=None,
            vendor=None,
        )
        for toner in http_toners:
            match toner.color:
                case "black":
                    result.toner_black = toner.level_pct
                case "cyan":
                    result.toner_cyan = toner.level_pct
                case "magenta":
                    result.toner_magenta = toner.level_pct
                case "yellow":
                    result.toner_yellow = toner.level_pct
        if not http_toners:
            logger.info("%s: SNMP unavailable, HTTP scraping found no toner data", ip_address)
        return result

    vendor = _detect_vendor(sys_descr)
    logger.debug("Polling %s — vendor: %s, descr: %.60s", ip_address, vendor or "unknown", sys_descr)

    status_text = "unknown"
    status_rows = await _snmp_walk(engine, target, comm, OID_PRINTER_STATUS_BASE)
    if status_rows:
        try:
            status_text = PRINTER_STATUS_MAP.get(int(status_rows[0][1]), "unknown")
        except (ValueError, TypeError):
            pass

    # Strategy 1: standard Printer MIB (RFC 3805)
    toners = await _get_standard_toners(engine, target, comm)

    # Strategy 2: Ricoh proprietary OIDs — try to get precise levels
    # when standard MIB returns -3 ("some remaining") for all supplies
    if toners and vendor == "ricoh":
        all_imprecise = all(t.level_pct in (-3, -2, None) for t in toners)
        if all_imprecise:
            logger.debug("%s: Ricoh standard MIB returns imprecise levels, trying proprietary OIDs", ip_address)
            toners = await _get_ricoh_toners(engine, target, comm, toners)

    # Strategy 3: vendor-specific SNMP fallback
    if not toners:
        if vendor == "brother":
            logger.debug("%s: standard MIB empty, trying Brother proprietary OIDs", ip_address)
            toners = await _get_brother_toners(engine, target, comm)

    # Strategy 4: HTTP scraping (HP EWS XML, works even with restricted SNMP)
    if not toners:
        logger.debug("%s: no SNMP toner data, trying HTTP scraping", ip_address)
        toners = await asyncio.to_thread(_get_toners_via_http, ip_address)

    # Strategy 5: HTTP fallback even when SNMP gives data but no toners found
    if not toners:
        toners = await asyncio.to_thread(_get_toners_via_http, ip_address)

    if not toners:
        logger.info(
            "%s (%s): no toner data via SNMP or HTTP",
            ip_address,
            vendor or "unknown",
        )

    result = PrinterStatus(
        is_online=True,
        status=status_text,
        toners=toners,
        sys_description=sys_descr,
        vendor=vendor,
    )
    for toner in toners:
        match toner.color:
            case "black":
                result.toner_black = toner.level_pct
            case "cyan":
                result.toner_cyan = toner.level_pct
            case "magenta":
                result.toner_magenta = toner.level_pct
            case "yellow":
                result.toner_yellow = toner.level_pct

    return result


def poll_printer(ip_address: str, community: str = "public") -> PrinterStatus:
    """Synchronous wrapper — runs the async poller in a new event loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    try:
        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(asyncio.run, _poll_printer_async(ip_address, community)).result()
        else:
            result = asyncio.run(_poll_printer_async(ip_address, community))
    except Exception:
        snmp_operations_total.labels(operation="poll_printer", result="error", reason="exception").inc()
        raise

    snmp_operations_total.labels(
        operation="poll_printer",
        result="success" if result.is_online else "offline",
        reason="none",
    ).inc()
    return result


OID_IF_PHYS_ADDR = "1.3.6.1.2.1.2.2.1.6"


async def _get_snmp_mac_async(ip_address: str, community: str = "public") -> str | None:
    """Query ifPhysAddress via SNMP to get MAC address."""
    engine = SnmpEngine()
    try:
        target = UdpTransportTarget((ip_address, 161), timeout=SNMP_TIMEOUT, retries=SNMP_RETRIES)
    except Exception:
        return None

    comm = CommunityData(community)
    try:
        async for err, _, _, vb in walkCmd(
            engine,
            comm,
            target,
            ContextData(),
            ObjectType(ObjectIdentity(OID_IF_PHYS_ADDR)),
            lexicographicMode=False,
        ):
            if err:
                break
            for _, val in vb:
                if hasattr(val, "asOctets"):
                    octets = val.asOctets()
                    if len(octets) == 6 and any(b != 0 for b in octets):
                        return ":".join(f"{b:02x}" for b in octets)
    except Exception:
        pass
    return None


def _get_mac_from_arp(ip_address: str) -> str | None:
    """Read MAC from system ARP table. Works with network_mode: host on Linux."""
    import subprocess

    # Ping to populate ARP cache
    try:
        subprocess.run(
            ["ping", "-c", "1", "-W", "1", ip_address],
            capture_output=True,
            timeout=3,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    try:
        with open("/proc/net/arp") as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                if len(parts) >= 4 and parts[0] == ip_address:
                    mac = parts[3].lower()
                    if mac != "00:00:00:00:00:00" and len(mac) == 17:
                        return mac
    except (FileNotFoundError, PermissionError):
        pass

    try:
        out = subprocess.run(
            ["ip", "neigh", "show", ip_address],
            capture_output=True,
            text=True,
            timeout=3,
        ).stdout.strip()
        if "lladdr" in out:
            parts = out.split()
            idx = parts.index("lladdr")
            if idx + 1 < len(parts):
                mac = parts[idx + 1].lower()
                if len(mac) == 17:
                    return mac
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def get_snmp_mac(ip_address: str, community: str = "public") -> str | None:
    """Get MAC via SNMP, with ARP table fallback."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    mac = None
    try:
        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                mac = pool.submit(asyncio.run, _get_snmp_mac_async(ip_address, community)).result()
        else:
            mac = asyncio.run(_get_snmp_mac_async(ip_address, community))
    except Exception:
        snmp_operations_total.labels(operation="get_mac", result="error", reason="exception").inc()
        return None

    # ARP fallback: works with network_mode: host on Linux
    if mac is None:
        mac = _get_mac_from_arp(ip_address)
        if mac:
            logger.debug("%s: MAC obtained from ARP table: %s", ip_address, mac)
            snmp_operations_total.labels(operation="get_mac", result="success", reason="arp_fallback").inc()
            return mac

    snmp_operations_total.labels(
        operation="get_mac",
        result="success" if mac else "offline",
        reason="snmp" if mac else "not_found",
    ).inc()
    return mac
