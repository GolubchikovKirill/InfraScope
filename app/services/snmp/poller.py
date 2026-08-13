from __future__ import annotations

import asyncio
import logging

from app.observability.metrics import snmp_operations_total

from ._pysnmp_compat import CommunityData, SnmpEngine, UdpTransportTarget
from .helpers import _detect_vendor
from .http_scrape import _get_toners_via_http
from .oids import (
    OID_PRINTER_STATUS_BASE,
    OID_SYS_DESCR,
    PRINTER_STATUS_MAP,
    SNMP_RETRIES,
    SNMP_TIMEOUT,
    PrinterStatus,
)
from .primitives import _snmp_get, _snmp_walk
from .tcp_fallback import _tcp_reachable
from .toner_strategies import _get_brother_toners, _get_ricoh_toners, _get_standard_toners

logger = logging.getLogger(__name__)


async def _poll_printer_async(ip_address: str, community: str = "public") -> PrinterStatus:
    engine = SnmpEngine()
    try:
        return await _poll_printer_async_inner(engine, ip_address, community)
    finally:
        # SnmpEngine opens a UDP socket lazily on first request and never
        # closes it on its own - across enough polling cycles that leaked
        # one file descriptor per call until the container hit its FD limit
        # (Errno 24) and every poll endpoint started returning 500. Must run
        # in the same event loop that issued the request; closing after
        # asyncio.run() returns is a no-op against a loop that's already gone.
        engine.closeDispatcher()


async def _poll_printer_async_inner(engine: SnmpEngine, ip_address: str, community: str) -> PrinterStatus:
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


async def _poll_printer_light_async(ip_address: str, community: str = "public") -> PrinterStatus:
    """Online/offline only - one SNMP GET, no toner walk or HTTP scraping."""
    engine = SnmpEngine()
    try:
        return await _poll_printer_light_async_inner(engine, ip_address, community)
    finally:
        engine.closeDispatcher()


async def _poll_printer_light_async_inner(engine: SnmpEngine, ip_address: str, community: str) -> PrinterStatus:
    try:
        target = UdpTransportTarget((ip_address, 161), timeout=SNMP_TIMEOUT, retries=SNMP_RETRIES)
    except Exception as e:
        logger.debug("Cannot create SNMP target for %s: %s", ip_address, e)
        return PrinterStatus(is_online=False, status="unreachable")

    comm = CommunityData(community)
    sys_descr = await _snmp_get(engine, target, comm, OID_SYS_DESCR)
    if sys_descr is not None:
        return PrinterStatus(
            is_online=True,
            status="online",
            sys_description=sys_descr,
            vendor=_detect_vendor(sys_descr),
        )

    reachable = await asyncio.to_thread(_tcp_reachable, ip_address)
    if reachable:
        return PrinterStatus(is_online=True, status="online (no SNMP)")
    return PrinterStatus(is_online=False, status="offline")


def poll_printer_light(ip_address: str, community: str = "public") -> PrinterStatus:
    """Cheap synchronous online/offline check for the frequent polling cadence.

    Skips the toner walk and HTTP-scraping fallbacks that poll_printer() does,
    so it's safe to run every cycle; the full toner poll runs on a slower
    cadence via poll_printer() instead.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    try:
        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(asyncio.run, _poll_printer_light_async(ip_address, community)).result()
        else:
            result = asyncio.run(_poll_printer_light_async(ip_address, community))
    except Exception:
        snmp_operations_total.labels(operation="poll_printer_light", result="error", reason="exception").inc()
        raise

    snmp_operations_total.labels(
        operation="poll_printer_light",
        result="success" if result.is_online else "offline",
        reason="none",
    ).inc()
    return result
