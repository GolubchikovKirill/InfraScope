from __future__ import annotations

import http.client
import logging
import re
import ssl as _ssl
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from .oids import TonerLevel

logger = logging.getLogger(__name__)

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
