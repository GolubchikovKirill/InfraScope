import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import func, select

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.api.routes._service_errors import conflict, not_found
from app.core.config import settings
from app.domains.inventory.models import Printer
from app.domains.inventory.printer_polling import (
    PrinterNotFoundError,
    UnsupportedPrinterPollError,
    invalidate_printer_cache,
    poll_all_printers_local,
    poll_single_printer_local,
)
from app.domains.inventory.schemas import (
    CartridgeIssueRequest,
    CartridgeStockMovementsPublic,
    CartridgeStockPublic,
    CartridgeStocksPublic,
    CartridgeStockUpdate,
    PrinterCreate,
    PrinterPublic,
    PrintersPublic,
    PrinterUpdate,
)
from app.domains.shared.schemas import Message
from app.services.cache import get_cached_model, set_cached_model
from app.services.cartridge_stock import (
    CartridgeStockMissingError,
    CartridgeStockQuantityError,
    issue_cartridge_stock,
    list_cartridge_movements,
    list_cartridge_stock,
    sync_cartridge_stock_from_printers,
    update_cartridge_stock,
)
from app.services.internal_services import _proxy_request
from app.services.mac_lookup import resolve_mac_for_ip_address
from app.services.smart_search import build_ilike_filter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["printers"])

CACHE_TTL = 30


def _get_printer_or_404(session: SessionDep, printer_id: uuid.UUID) -> Printer:
    printer = session.get(Printer, printer_id)
    if not printer:
        raise not_found("Printer not found")
    return printer


def _check_unique_ip(session: SessionDep, ip_address: str, *, excluded_printer_id: uuid.UUID | None = None) -> None:
    filters = [Printer.ip_address == ip_address]
    if excluded_printer_id is not None:
        filters.append(Printer.id != excluded_printer_id)
    existing = session.exec(select(Printer).where(*filters)).first()
    if existing:
        status_code = 409 if excluded_printer_id is not None else 400
        raise conflict("Printer with this IP already exists", status_code=status_code)


async def _resolve_mac_for_printer(printer: Printer) -> str | None:
    if not (printer.connection_type == "ip" and printer.ip_address):
        return None
    return await resolve_mac_for_ip_address(
        printer.ip_address,
        snmp_community=printer.snmp_community,
        prefer_snmp=printer.printer_type != "label",
    )


@router.get("/cartridges", response_model=CartridgeStocksPublic)
def read_cartridge_stock(
    session: SessionDep,
    current_user: CurrentUser,
    search: str | None = None,
) -> CartridgeStocksPublic:
    del current_user
    rows = list_cartridge_stock(session, search=search)
    return CartridgeStocksPublic(data=rows, count=len(rows))


@router.post(
    "/cartridges/sync",
    response_model=CartridgeStocksPublic,
    dependencies=[Depends(get_current_active_superuser)],
)
def sync_cartridge_stock(session: SessionDep) -> CartridgeStocksPublic:
    rows = sync_cartridge_stock_from_printers(session)
    return CartridgeStocksPublic(data=rows, count=len(rows))


@router.patch(
    "/cartridges/{stock_id}",
    response_model=CartridgeStockPublic,
    dependencies=[Depends(get_current_active_superuser)],
)
def patch_cartridge_stock(
    stock_id: uuid.UUID,
    payload: CartridgeStockUpdate,
    session: SessionDep,
    current_user: CurrentUser,
) -> CartridgeStockPublic:
    try:
        return update_cartridge_stock(session, stock_id, payload, actor=current_user.email)
    except CartridgeStockMissingError as exc:
        raise HTTPException(status_code=404, detail="Cartridge stock item not found") from exc


@router.post(
    "/cartridges/{stock_id}/issue",
    response_model=CartridgeStockPublic,
    dependencies=[Depends(get_current_active_superuser)],
)
def issue_cartridge(
    stock_id: uuid.UUID,
    payload: CartridgeIssueRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> CartridgeStockPublic:
    try:
        return issue_cartridge_stock(session, stock_id, payload, actor=current_user.email)
    except CartridgeStockMissingError as exc:
        raise HTTPException(status_code=404, detail="Cartridge stock item not found") from exc
    except CartridgeStockQuantityError as exc:
        raise HTTPException(status_code=409, detail="Not enough cartridges on stock") from exc


@router.get("/cartridges/{stock_id}/movements", response_model=CartridgeStockMovementsPublic)
def read_cartridge_movements(
    stock_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
) -> CartridgeStockMovementsPublic:
    del current_user
    try:
        rows = list_cartridge_movements(session, stock_id, limit=limit)
    except CartridgeStockMissingError as exc:
        raise HTTPException(status_code=404, detail="Cartridge stock item not found") from exc
    return CartridgeStockMovementsPublic(data=rows, count=len(rows))


@router.get("/", response_model=PrintersPublic)
async def read_printers(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=200, le=500),
    store_name: str | None = None,
    printer_type: str = Query(default="laser"),
) -> PrintersPublic:
    cache_key = f"printers:{printer_type}:{store_name or ''}:{skip}:{limit}"
    if cached := await get_cached_model(cache_key, PrintersPublic):
        return cached

    statement = select(Printer).where(Printer.printer_type == printer_type)
    count_stmt = select(func.count()).select_from(Printer).where(Printer.printer_type == printer_type)
    if store_name:
        flt = build_ilike_filter(
            [
                Printer.store_name,
                Printer.model,
                Printer.host_pc,
                Printer.ip_address,
                Printer.mac_address,
            ],
            store_name,
        )
        if flt is not None:
            statement = statement.where(flt)
            count_stmt = count_stmt.where(flt)
    count = session.exec(count_stmt).one()
    printers = session.exec(statement.offset(skip).limit(limit).order_by(Printer.store_name)).all()
    result = PrintersPublic(data=printers, count=count)

    await set_cached_model(cache_key, result, ttl=CACHE_TTL)

    return result


@router.post("/", response_model=PrinterPublic, dependencies=[Depends(get_current_active_superuser)])
async def create_printer(session: SessionDep, printer_in: PrinterCreate) -> Printer:
    if printer_in.connection_type == "ip" and printer_in.ip_address:
        _check_unique_ip(session, printer_in.ip_address)
    printer = Printer(**printer_in.model_dump())
    if printer.connection_type == "ip" and printer.ip_address and not printer.mac_address:
        printer.mac_address = await _resolve_mac_for_printer(printer)
        printer.mac_status = "verified" if printer.mac_address else None
    session.add(printer)
    session.commit()
    session.refresh(printer)
    await invalidate_printer_cache()
    return printer


@router.get("/{printer_id}", response_model=PrinterPublic)
def read_printer(printer_id: uuid.UUID, session: SessionDep, current_user: CurrentUser) -> Printer:
    return _get_printer_or_404(session, printer_id)


@router.patch("/{printer_id}", response_model=PrinterPublic, dependencies=[Depends(get_current_active_superuser)])
async def update_printer(session: SessionDep, printer_id: uuid.UUID, printer_in: PrinterUpdate) -> Printer:
    printer = _get_printer_or_404(session, printer_id)
    update_data = printer_in.model_dump(exclude_unset=True)
    if "ip_address" in update_data and update_data["ip_address"] is not None:
        _check_unique_ip(session, update_data["ip_address"], excluded_printer_id=printer_id)
    printer.updated_at = datetime.now(UTC)
    ip_changed = "ip_address" in update_data and update_data.get("ip_address") != printer.ip_address
    explicit_mac = "mac_address" in update_data
    printer.sqlmodel_update(update_data)
    if (
        printer.connection_type == "ip"
        and printer.ip_address
        and ip_changed
        and not explicit_mac
    ):
        resolved_mac = await _resolve_mac_for_printer(printer)
        if resolved_mac:
            printer.mac_address = resolved_mac
            printer.mac_status = "verified"
    session.add(printer)
    session.commit()
    session.refresh(printer)
    await invalidate_printer_cache()
    return printer


@router.delete("/{printer_id}", dependencies=[Depends(get_current_active_superuser)])
async def delete_printer(session: SessionDep, printer_id: uuid.UUID) -> Message:
    printer = _get_printer_or_404(session, printer_id)
    session.delete(printer)
    session.commit()
    await invalidate_printer_cache()
    return Message(message="Printer deleted")


# -- Poll endpoints ----------------------------------------------------------


@router.post("/{printer_id}/poll", response_model=PrinterPublic)
async def poll_single_printer(printer_id: uuid.UUID, session: SessionDep, current_user: CurrentUser) -> Printer:
    del current_user
    try:
        return await poll_single_printer_local(session=session, printer_id=printer_id)
    except PrinterNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Printer not found") from exc
    except UnsupportedPrinterPollError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/poll-all", response_model=PrintersPublic)
async def poll_all_printers(
    session: SessionDep,
    current_user: CurrentUser,
    printer_type: str = Query(default="laser"),
) -> PrintersPublic:
    del current_user
    if settings.POLLING_SERVICE_ENABLED:
        payload = await _proxy_request(
            base_url=settings.POLLING_SERVICE_URL,
            method="POST",
            path="/poll/printers",
            params={"printer_type": printer_type},
        )
        return PrintersPublic.model_validate(payload)

    return await poll_all_printers_local(session=session, printer_type=printer_type)
