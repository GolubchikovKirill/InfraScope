import logging
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.core.config import settings
from app.domains.inventory.media_polling import invalidate_media_player_cache
from app.domains.inventory.models import MediaPlayer, Printer
from app.domains.inventory.printer_polling import invalidate_printer_cache
from app.domains.inventory.schemas import (
    MacRediscoveryItem,
    MacRediscoveryRequest,
    MacRediscoveryResponse,
    PrinterCreate,
    PrinterPublic,
    ScanProgress,
    ScanRequest,
    ScanResults,
    SmartNetworkSearchPublic,
    SmartNetworkSearchRequest,
)
from app.services.app_settings import get_general_settings
from app.services.event_log import write_event_log
from app.services.internal_services import _proxy_request
from app.services.mac_lookup import resolve_mac_for_ip_address
from app.services.mac_rediscovery import MacRediscoveryTarget, resolve_devices_by_mac
from app.services.scanner import get_scan_progress, get_scan_results, scan_subnet, smart_probe_network
from app.services.smart_search import text_matches_query

logger = logging.getLogger(__name__)

router = APIRouter(tags=["scanner"])


async def _run_scan(subnet: str, ports: str, known_printers: list[dict]) -> None:
    try:
        await scan_subnet(subnet, ports, known_printers)
    except Exception as e:
        logger.error("Scan failed: %s", e)


def _candidate_confidence(is_high: bool, is_medium: bool) -> str:
    if is_high:
        return "high"
    if is_medium:
        return "medium"
    return "low"


def _match_hostname_token(hostname: str | None, token: str | None) -> bool:
    if not token:
        return True
    return text_matches_query([hostname], token)


def _split_subnets(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _classify_computer(device: dict, token: str | None) -> tuple[str, str] | None:
    hostname = device.get("hostname")
    ports = set(device.get("open_ports") or [])
    has_mgr = _match_hostname_token(hostname, token)
    has_rdp = 3389 in ports
    has_smb = 445 in ports or 139 in ports
    has_rpc = 135 in ports

    is_high = bool(has_mgr and (has_rdp or has_smb))
    is_medium = bool((has_rdp and has_smb) or (has_mgr and has_rpc))
    if not (is_high or is_medium or has_mgr or has_rdp or has_smb):
        return None

    if is_high:
        reason = "hostname+windows_ports"
    elif is_medium:
        reason = "windows_ports"
    else:
        reason = "hostname_pattern"
    return _candidate_confidence(is_high, is_medium), reason


def _classify_cash_register(device: dict, token: str | None) -> tuple[str, str] | None:
    hostname = device.get("hostname")
    ports = set(device.get("open_ports") or [])
    has_kkm = _match_hostname_token(hostname, token)
    has_netsupport = 5405 in ports
    has_windows_ports = 3389 in ports or 445 in ports or 139 in ports

    is_high = bool(has_kkm and (has_netsupport or has_windows_ports))
    is_medium = bool(has_netsupport and has_windows_ports)
    if not (is_high or is_medium or has_kkm):
        return None

    if is_high:
        reason = "hostname+cash_ports"
    elif is_medium:
        reason = "cash_ports"
    else:
        reason = "hostname_pattern"
    return _candidate_confidence(is_high, is_medium), reason


@router.post(
    "/scan",
    response_model=ScanProgress,
    dependencies=[Depends(get_current_active_superuser)],
)
async def start_scan(
    body: ScanRequest,
    background_tasks: BackgroundTasks,
    session: SessionDep,
) -> dict:
    """Start a network scan (runs in background)."""
    printers = session.exec(select(Printer)).all()
    known = [
        {
            "id": str(p.id),
            "ip_address": p.ip_address,
            "mac_address": p.mac_address,
            "store_name": p.store_name,
        }
        for p in printers
    ]
    if settings.DISCOVERY_SERVICE_ENABLED:
        return await _proxy_request(
            base_url=settings.DISCOVERY_SERVICE_URL,
            method="POST",
            path="/discover/printers/scan",
            json_body={
                "subnet": body.subnet,
                "ports": body.ports,
                "known_printers": known,
            },
        )
    background_tasks.add_task(_run_scan, body.subnet, body.ports, known)
    return {"status": "running", "scanned": 0, "total": 0, "found": 0, "message": None}


@router.get("/status", response_model=ScanProgress)
async def scan_status(current_user: CurrentUser) -> dict:
    """Get current scan progress."""
    if settings.DISCOVERY_SERVICE_ENABLED:
        return await _proxy_request(
            base_url=settings.DISCOVERY_SERVICE_URL,
            method="GET",
            path="/discover/printers/status",
        )
    return await get_scan_progress()


@router.get("/results", response_model=ScanResults)
async def scan_results(current_user: CurrentUser) -> dict:
    """Get results of the last scan."""
    if settings.DISCOVERY_SERVICE_ENABLED:
        payload = await _proxy_request(
            base_url=settings.DISCOVERY_SERVICE_URL,
            method="GET",
            path="/discover/printers/results",
        )
        return ScanResults.model_validate(payload).model_dump()
    progress = await get_scan_progress()
    devices = await get_scan_results()
    return {"progress": progress, "devices": devices}


@router.post(
    "/add",
    response_model=PrinterPublic,
    dependencies=[Depends(get_current_active_superuser)],
)
async def add_discovered_printer(
    body: PrinterCreate,
    session: SessionDep,
) -> Printer:
    """Add a discovered device as a monitored printer."""
    existing = session.exec(select(Printer).where(Printer.ip_address == body.ip_address)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Printer with this IP already exists")
    printer = Printer(**body.model_dump())
    if printer.connection_type == "ip" and printer.ip_address and not printer.mac_address:
        printer.mac_address = await resolve_mac_for_ip_address(
            printer.ip_address,
            snmp_community=printer.snmp_community,
            prefer_snmp=printer.printer_type != "label",
        )
        printer.mac_status = "verified" if printer.mac_address else None
    session.add(printer)
    session.commit()
    session.refresh(printer)
    return printer


@router.post(
    "/update-ip/{printer_id}",
    response_model=PrinterPublic,
    dependencies=[Depends(get_current_active_superuser)],
)
async def update_printer_ip(
    printer_id: str,
    session: SessionDep,
    new_ip: str = "",
    new_mac: str | None = None,
) -> Printer:
    """Update printer IP (when DHCP changed it)."""
    import uuid

    printer = session.get(Printer, uuid.UUID(printer_id))
    if not printer:
        raise HTTPException(status_code=404, detail="Printer not found")
    old_ip = printer.ip_address
    if new_ip:
        conflict = session.exec(select(Printer).where(Printer.ip_address == new_ip, Printer.id != printer.id)).first()
        if conflict:
            raise HTTPException(status_code=409, detail="Another printer already has this IP")
        printer.ip_address = new_ip
        if old_ip != new_ip:
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
    if new_mac:
        printer.mac_address = new_mac
    elif new_ip:
        resolved_mac = await resolve_mac_for_ip_address(
            new_ip,
            snmp_community=printer.snmp_community,
            prefer_snmp=printer.printer_type != "label",
        )
        if resolved_mac:
            printer.mac_address = resolved_mac
            printer.mac_status = "verified"
    printer.updated_at = datetime.now(UTC)
    session.add(printer)
    session.commit()
    session.refresh(printer)
    return printer


@router.post(
    "/rediscover-by-mac",
    response_model=MacRediscoveryResponse,
    dependencies=[Depends(get_current_active_superuser)],
)
async def rediscover_by_mac(body: MacRediscoveryRequest, session: SessionDep) -> MacRediscoveryResponse:
    """Find known devices by MAC and update IP addresses when DHCP changed them."""
    general = get_general_settings(session)
    subnets = body.subnets or _split_subnets(general["scan_subnet"])
    targets: list[MacRediscoveryTarget] = []
    printers_by_id: dict[str, Printer] = {}
    players_by_id: dict[str, MediaPlayer] = {}

    if "printer" in body.device_kinds:
        printers = session.exec(select(Printer).where(Printer.mac_address.isnot(None))).all()
        printers_by_id = {str(printer.id): printer for printer in printers}
        targets.extend(
            MacRediscoveryTarget(
                device_kind="printer",
                entity_id=str(printer.id),
                name=printer.store_name,
                current_ip=printer.ip_address,
                mac_address=printer.mac_address or "",
            )
            for printer in printers
        )

    if "media_player" in body.device_kinds:
        players = session.exec(select(MediaPlayer).where(MediaPlayer.mac_address.isnot(None))).all()
        players_by_id = {str(player.id): player for player in players}
        targets.extend(
            MacRediscoveryTarget(
                device_kind="media_player",
                entity_id=str(player.id),
                name=player.name,
                current_ip=player.ip_address,
                mac_address=player.mac_address or "",
            )
            for player in players
        )

    matches = await resolve_devices_by_mac(targets, subnets=subnets, session=session)
    matches_by_target = {(match.target.device_kind, match.target.entity_id): match for match in matches}
    printer_ip_owner = {
        ip_address: str(printer_id)
        for printer_id, ip_address in session.exec(
            select(Printer.id, Printer.ip_address).where(Printer.ip_address.isnot(None))
        ).all()
        if ip_address
    }
    media_ip_owner = {
        ip_address: str(player_id)
        for player_id, ip_address in session.exec(
            select(MediaPlayer.id, MediaPlayer.ip_address).where(MediaPlayer.ip_address.isnot(None))
        ).all()
        if ip_address
    }
    items: list[MacRediscoveryItem] = []
    updated = 0

    for target in targets:
        match = matches_by_target.get((target.device_kind, target.entity_id))
        if not match:
            items.append(
                MacRediscoveryItem(
                    device_kind=target.device_kind,
                    id=target.entity_id,
                    name=target.name,
                    mac_address=target.mac_address,
                    old_ip=target.current_ip,
                    status="not_found",
                    message="MAC not found in ARP table after scan",
                )
            )
            continue

        if not match.moved:
            items.append(
                MacRediscoveryItem(
                    device_kind=target.device_kind,
                    id=target.entity_id,
                    name=target.name,
                    mac_address=match.normalized_mac,
                    old_ip=target.current_ip,
                    new_ip=match.new_ip,
                    status="unchanged",
                    message="IP address is unchanged",
                )
            )
            continue

        status: str = "found"
        message = "New IP address found"
        if target.device_kind == "printer":
            entity = printers_by_id.get(target.entity_id)
            conflict = printer_ip_owner.get(match.new_ip) not in {None, target.entity_id}
        else:
            entity = players_by_id.get(target.entity_id)
            conflict = media_ip_owner.get(match.new_ip) not in {None, target.entity_id}

        if conflict:
            status = "conflict"
            message = "New IP already belongs to another device"
        elif body.apply and entity:
            old_ip = target.current_ip
            entity.ip_address = match.new_ip
            entity.updated_at = datetime.now(UTC)
            session.add(entity)
            write_event_log(
                session,
                category="network",
                event_type="ip_changed",
                severity="warning",
                device_kind=target.device_kind,
                device_name=target.name,
                ip_address=match.new_ip,
                message=f"{target.name} moved IP: {old_ip} -> {match.new_ip}",
            )
            status = "updated"
            message = "IP address updated"
            updated += 1

        items.append(
            MacRediscoveryItem(
                device_kind=target.device_kind,
                id=target.entity_id,
                name=target.name,
                mac_address=match.normalized_mac,
                old_ip=target.current_ip,
                new_ip=match.new_ip,
                status=status,
                message=message,
            )
        )

    if updated:
        session.commit()
        await invalidate_printer_cache()
        await invalidate_media_player_cache()

    return MacRediscoveryResponse(data=items, count=len(items), updated=updated)


@router.get("/settings")
async def get_scanner_settings(session: SessionDep, current_user: CurrentUser) -> dict:
    """Get default scanner settings."""
    general = get_general_settings(session)
    return {
        "subnet": general["scan_subnet"],
        "ports": general["scan_ports"],
        "dns_search_suffixes": general["dns_search_suffixes"],
        "max_hosts": settings.SCAN_MAX_HOSTS,
        "tcp_timeout": settings.SCAN_TCP_TIMEOUT,
        "tcp_retries": settings.SCAN_TCP_RETRIES,
        "tcp_concurrency": settings.SCAN_TCP_CONCURRENCY,
    }


@router.post("/smart-search/computers", response_model=SmartNetworkSearchPublic)
async def smart_search_computers(
    body: SmartNetworkSearchRequest, session: SessionDep, current_user: CurrentUser
) -> SmartNetworkSearchPublic:
    del current_user
    general = get_general_settings(session)
    used_subnet = body.subnet or general["scan_subnet"]
    used_ports = body.ports or "3389,445,139,135,22"
    token = body.hostname_contains or "-MGR-"

    probed = await smart_probe_network(used_subnet, used_ports)
    candidates = []
    for row in probed:
        classified = _classify_computer(row, token)
        if not classified:
            continue
        confidence, reason = classified
        candidates.append(
            {
                "ip": row["ip"],
                "hostname": row.get("hostname"),
                "open_ports": row.get("open_ports", []),
                "confidence": confidence,
                "reason": reason,
            }
        )
    rank = {"high": 0, "medium": 1, "low": 2}
    candidates.sort(key=lambda item: (rank.get(item["confidence"], 3), item.get("hostname") or item["ip"]))
    limited = candidates[: body.limit]
    return SmartNetworkSearchPublic(
        data=limited,
        count=len(limited),
        used_subnet=used_subnet,
        used_ports=used_ports,
    )


@router.post("/smart-search/cash-registers", response_model=SmartNetworkSearchPublic)
async def smart_search_cash_registers(
    body: SmartNetworkSearchRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> SmartNetworkSearchPublic:
    del current_user
    general = get_general_settings(session)
    used_subnet = body.subnet or general["scan_subnet"]
    used_ports = body.ports or "5405,3389,445,139"
    token = body.hostname_contains or "KKM"

    probed = await smart_probe_network(used_subnet, used_ports)
    candidates = []
    for row in probed:
        classified = _classify_cash_register(row, token)
        if not classified:
            continue
        confidence, reason = classified
        candidates.append(
            {
                "ip": row["ip"],
                "hostname": row.get("hostname"),
                "open_ports": row.get("open_ports", []),
                "confidence": confidence,
                "reason": reason,
            }
        )
    rank = {"high": 0, "medium": 1, "low": 2}
    candidates.sort(key=lambda item: (rank.get(item["confidence"], 3), item.get("hostname") or item["ip"]))
    limited = candidates[: body.limit]
    return SmartNetworkSearchPublic(
        data=limited,
        count=len(limited),
        used_subnet=used_subnet,
        used_ports=used_ports,
    )
