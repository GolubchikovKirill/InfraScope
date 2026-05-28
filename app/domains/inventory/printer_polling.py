from __future__ import annotations

import asyncio
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

from sqlmodel import Session, select

from app.core.redis import get_redis
from app.core.config import settings
from app.domains.inventory.models import Printer
from app.domains.inventory.schemas import PrintersPublic
from app.observability.metrics import printer_polls_total, set_device_counts
from app.services.cache import invalidate_entity_cache
from app.services.event_log import write_event_log
from app.services.mac_rediscovery import MacRediscoveryTarget, resolve_devices_by_mac
from app.services.ml_snapshots import write_printer_snapshots
from app.services.ping import check_port
from app.services.poll_resilience import apply_poll_outcome, is_circuit_open, poll_jitter_sync
from app.services.snmp import get_snmp_mac, poll_printer

logger = logging.getLogger(__name__)

class PrinterNotFoundError(LookupError):
    pass


class UnsupportedPrinterPollError(ValueError):
    pass


async def invalidate_printer_cache() -> None:
    await invalidate_entity_cache("printers")


def _record_status_change(session: Session, printer: Printer, was_online: bool | None) -> None:
    if was_online is None or was_online == printer.is_online:
        return
    write_event_log(
        session,
        category="device",
        event_type="device_online" if printer.is_online else "device_offline",
        severity="info" if printer.is_online else "warning",
        device_kind="printer",
        device_name=printer.store_name,
        ip_address=printer.ip_address,
        message=f"Printer '{printer.store_name}' is now {'online' if printer.is_online else 'offline'}",
    )


def poll_one_printer(printer: Printer) -> tuple[str, object | None, str | None]:
    if printer.connection_type == "usb" or not printer.ip_address:
        return "", None, None
    ip = printer.ip_address
    try:
        poll_jitter_sync()
        if printer.printer_type == "label":
            online = check_port(ip)
            return ip, {"is_online": online}, None
        result = poll_printer(ip, printer.snmp_community)
        current_mac = get_snmp_mac(ip, printer.snmp_community) if result.is_online else None
        return ip, result, current_mac
    except Exception as exc:
        logger.warning("Poll failed for %s: %s", ip, exc)
        return ip, None, None


def verify_printer_mac(printer: Printer, current_mac: str | None) -> str | None:
    if current_mac is None:
        return "unavailable"
    if not printer.mac_address:
        printer.mac_address = current_mac
        return "verified"
    if printer.mac_address.lower() == current_mac.lower():
        return "verified"
    return "mismatch"


def poll_printer_batch(printers: list[Printer]) -> dict[str, tuple[object | None, str | None]]:
    results: dict[str, tuple[object | None, str | None]] = {}
    max_workers = max(1, min(settings.PRINTER_POLL_MAX_WORKERS, len(printers)))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(poll_one_printer, printer): printer.ip_address for printer in printers}
        for future in as_completed(futures):
            ip = futures[future]
            try:
                _, result, mac = future.result()
            except Exception as exc:
                logger.warning("Poll failed for %s: %s", ip, exc)
                result, mac = None, None
            results[ip] = (result, mac)
    return results


async def find_printer_ip_by_mac(printer: Printer) -> str | None:
    if not printer.mac_address:
        return None
    matches = await resolve_devices_by_mac(
        [
            MacRediscoveryTarget(
                device_kind="printer",
                entity_id=str(printer.id),
                name=printer.store_name,
                current_ip=printer.ip_address,
                mac_address=printer.mac_address,
            )
        ]
    )
    return matches[0].new_ip if matches else None


async def poll_single_printer_local(*, session: Session, printer_id: uuid.UUID) -> Printer:
    printer = session.get(Printer, printer_id)
    if not printer:
        raise PrinterNotFoundError("Printer not found")

    was_online = printer.is_online
    if printer.connection_type == "usb" or not printer.ip_address:
        printer_polls_total.labels(mode="single", printer_type=printer.printer_type, result="unsupported").inc()
        raise UnsupportedPrinterPollError("USB printers cannot be polled")

    if printer.printer_type == "label":
        online = await asyncio.to_thread(check_port, printer.ip_address)
        printer.is_online = online
        printer.status = "online" if online else "offline"
        printer.mac_status = None
        printer_polls_total.labels(
            mode="single",
            printer_type=printer.printer_type,
            result="online" if online else "offline",
        ).inc()
    else:
        _, result, current_mac = await asyncio.to_thread(poll_one_printer, printer)
        if result is None or not result.is_online:
            if printer.mac_address:
                new_ip = await find_printer_ip_by_mac(printer)
                if new_ip and new_ip != printer.ip_address:
                    old_ip = printer.ip_address
                    logger.info(
                        "Printer %s (%s) found at new IP %s (was %s)",
                        printer.store_name,
                        printer.mac_address,
                        new_ip,
                        printer.ip_address,
                    )
                    conflict = session.exec(
                        select(Printer).where(
                            Printer.ip_address == new_ip,
                            Printer.id != printer.id,
                        )
                    ).first()
                    if not conflict:
                        printer.ip_address = new_ip
                        write_event_log(
                            session,
                            category="network",
                            event_type="ip_changed",
                            severity="warning",
                            device_kind="printer",
                            device_name=printer.store_name,
                            ip_address=new_ip,
                            message=f"Printer '{printer.store_name}' moved IP: {old_ip} -> {new_ip}",
                        )
                        _, result, current_mac = await asyncio.to_thread(poll_one_printer, printer)

            if result is None:
                printer.is_online = False
                printer.status = "error"
                printer.mac_status = "unavailable"
                printer_polls_total.labels(mode="single", printer_type=printer.printer_type, result="error").inc()
            elif not result.is_online:
                printer.is_online = False
                printer.status = "offline"
                printer.mac_status = "unavailable"
                printer_polls_total.labels(mode="single", printer_type=printer.printer_type, result="offline").inc()
            else:
                _apply_full_printer_result(printer, result, current_mac)
                printer_polls_total.labels(mode="single", printer_type=printer.printer_type, result="online").inc()
        else:
            _apply_full_printer_result(printer, result, current_mac)
            printer_polls_total.labels(mode="single", printer_type=printer.printer_type, result="online").inc()

    printer.last_polled_at = datetime.now(UTC)
    _record_status_change(session, printer, was_online)
    write_printer_snapshots(session, printer, source="single_poll")
    session.add(printer)
    session.commit()
    session.refresh(printer)
    await invalidate_printer_cache()
    return printer


async def poll_all_printers_local(*, session: Session, printer_type: str = "laser") -> PrintersPublic:
    lock_key = f"lock:poll-all:printers:{printer_type}"
    lock_acquired = True
    try:
        redis = await get_redis()
        lock_acquired = bool(await redis.set(lock_key, "1", ex=45, nx=True))
    except Exception:
        lock_acquired = True

    all_printers = session.exec(select(Printer).where(Printer.printer_type == printer_type)).all()
    set_device_counts(
        kind="printer",
        total=len(all_printers),
        online=sum(1 for printer in all_printers if printer.is_online),
    )
    if not lock_acquired:
        logger.info("Skipping duplicate poll-all request for printers (%s): lock busy", printer_type)
        return PrintersPublic(data=all_printers, count=len(all_printers))
    if not all_printers:
        return PrintersPublic(data=[], count=0)

    printers = [printer for printer in all_printers if printer.connection_type != "usb" and printer.ip_address]
    if not printers:
        return PrintersPublic(data=all_printers, count=len(all_printers))

    poll_targets: list[Printer] = []
    for printer in printers:
        if await is_circuit_open("printer", str(printer.id)):
            printer_polls_total.labels(mode="all", printer_type=printer.printer_type, result="skipped").inc()
            continue
        poll_targets.append(printer)

    printer_map = {printer.ip_address: printer for printer in poll_targets}
    try:
        poll_results = await asyncio.to_thread(poll_printer_batch, poll_targets) if poll_targets else {}
        offline_with_mac: list[Printer] = []

        for ip, (result, current_mac) in poll_results.items():
            printer = printer_map[ip]
            previous_online = printer.is_online
            raw_online = bool(
                result
                and (
                    (isinstance(result, dict) and result.get("is_online"))
                    or (hasattr(result, "is_online") and result.is_online)
                )
            )
            effective_online = await apply_poll_outcome(
                kind="printer",
                entity_id=str(printer.id),
                previous_effective_online=previous_online,
                probed_online=raw_online,
                probed_error=result is None,
            )
            if result is None:
                printer.is_online = effective_online
                printer.status = "error" if not effective_online else (printer.status or "online")
                printer.mac_status = "unavailable"
                printer_polls_total.labels(
                    mode="all",
                    printer_type=printer.printer_type,
                    result="error" if not effective_online else "offline_pending",
                ).inc()
                if (not effective_online) and printer.mac_address:
                    offline_with_mac.append(printer)
            elif isinstance(result, dict):
                printer.is_online = effective_online
                printer.status = "online" if effective_online else "offline"
                printer.mac_status = None
                printer_polls_total.labels(
                    mode="all",
                    printer_type=printer.printer_type,
                    result="online" if effective_online else "offline",
                ).inc()
                if (not effective_online) and printer.mac_address:
                    offline_with_mac.append(printer)
            else:
                printer.is_online = effective_online
                if effective_online:
                    _apply_full_printer_result(printer, result, current_mac)
                else:
                    printer.status = "offline"
                    printer.mac_status = verify_printer_mac(printer, current_mac)
                printer_polls_total.labels(
                    mode="all",
                    printer_type=printer.printer_type,
                    result="online" if effective_online else "offline",
                ).inc()
                if (not effective_online) and printer.mac_address:
                    offline_with_mac.append(printer)
            printer.last_polled_at = datetime.now(UTC)
            _record_status_change(session, printer, previous_online)
            write_printer_snapshots(session, printer, source="bulk_poll")
            session.add(printer)

        await _relocate_offline_printers(session, offline_with_mac)

        session.commit()
        result_printers = session.exec(select(Printer).where(Printer.printer_type == printer_type)).all()
        set_device_counts(
            kind="printer",
            total=len(result_printers),
            online=sum(1 for printer in result_printers if printer.is_online),
        )

        await invalidate_printer_cache()
        return PrintersPublic(data=result_printers, count=len(result_printers))
    finally:
        if lock_acquired:
            try:
                redis = await get_redis()
                await redis.delete(lock_key)
            except Exception:
                pass


def _apply_full_printer_result(printer: Printer, result, current_mac: str | None) -> None:
    printer.is_online = result.is_online
    printer.status = result.status
    printer.toner_black = result.toner_black
    printer.toner_cyan = result.toner_cyan
    printer.toner_magenta = result.toner_magenta
    printer.toner_yellow = result.toner_yellow
    printer.mac_status = verify_printer_mac(printer, current_mac)


async def _relocate_offline_printers(session: Session, offline_with_mac: list[Printer]) -> None:
    targets = [
        MacRediscoveryTarget(
            device_kind="printer",
            entity_id=str(printer.id),
            name=printer.store_name,
            current_ip=printer.ip_address,
            mac_address=printer.mac_address,
        )
        for printer in offline_with_mac
        if printer.mac_address
    ]
    matches = await resolve_devices_by_mac(targets)
    matches_by_id = {match.target.entity_id: match for match in matches}

    for printer in offline_with_mac:
        match = matches_by_id.get(str(printer.id))
        new_ip = match.new_ip if match else None
        if not new_ip or new_ip == printer.ip_address:
            continue

        conflict = session.exec(
            select(Printer).where(
                Printer.ip_address == new_ip,
                Printer.id != printer.id,
            )
        ).first()
        if conflict:
            continue

        old_ip = printer.ip_address
        printer.ip_address = new_ip
        _, new_result, new_mac = await asyncio.to_thread(poll_one_printer, printer)
        if new_result and (
            (isinstance(new_result, dict) and new_result.get("is_online"))
            or (hasattr(new_result, "is_online") and new_result.is_online)
        ):
            if isinstance(new_result, dict):
                printer.is_online = new_result["is_online"]
                printer.status = "online"
            else:
                _apply_full_printer_result(printer, new_result, new_mac)
            logger.info(
                "Auto-relocated %s: %s -> %s (MAC %s)",
                printer.store_name,
                old_ip,
                new_ip,
                printer.mac_address,
            )
            write_event_log(
                session,
                category="network",
                event_type="ip_changed",
                severity="warning",
                device_kind="printer",
                device_name=printer.store_name,
                ip_address=new_ip,
                message=f"Printer '{printer.store_name}' moved IP: {old_ip} -> {new_ip}",
            )
        else:
            printer.ip_address = old_ip
        write_printer_snapshots(session, printer, source="bulk_poll_relocated")
        session.add(printer)
