from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime

from sqlmodel import Session, select

from app.domains.inventory.models import CartridgeStock, CartridgeStockMovement, Printer
from app.domains.inventory.schemas import CartridgeIssueRequest, CartridgeStockUpdate

_TONER_FIELDS: tuple[tuple[str, str], ...] = (
    ("black", "toner_black_name"),
    ("cyan", "toner_cyan_name"),
    ("magenta", "toner_magenta_name"),
    ("yellow", "toner_yellow_name"),
)


class CartridgeStockMissingError(LookupError):
    pass


class CartridgeStockQuantityError(ValueError):
    pass


def _normalize_cartridge_name(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.strip().split())
    return normalized[:128] if normalized else None


def sync_cartridge_stock_from_printers(session: Session) -> list[CartridgeStock]:
    printers = session.exec(select(Printer).where(Printer.printer_type == "laser")).all()
    discovered: dict[str, dict] = {}
    model_sets: dict[str, set[str]] = defaultdict(set)

    for printer in printers:
        for color, field_name in _TONER_FIELDS:
            cartridge_name = _normalize_cartridge_name(getattr(printer, field_name))
            if not cartridge_name:
                continue
            if cartridge_name not in discovered:
                discovered[cartridge_name] = {"toner_color": color, "printer_count": 0}
            discovered[cartridge_name]["printer_count"] += 1
            model_sets[cartridge_name].add(printer.model)

    now = datetime.now(UTC)
    rows: list[CartridgeStock] = []
    for cartridge_name, meta in sorted(discovered.items()):
        row = session.exec(select(CartridgeStock).where(CartridgeStock.cartridge_name == cartridge_name)).first()
        if row is None:
            row = CartridgeStock(cartridge_name=cartridge_name)
        elif not row.is_active:
            # An inactive row is an explicit inventory tombstone. Do not
            # resurrect it during printer metadata synchronization.
            continue
        row.toner_color = meta["toner_color"]
        row.compatible_printer_models = ", ".join(sorted(model_sets[cartridge_name]))[:1024]
        row.printer_count = meta["printer_count"]
        row.is_active = True
        row.last_synced_at = now
        row.updated_at = now
        session.add(row)
        rows.append(row)

    session.commit()
    for row in rows:
        session.refresh(row)
    return rows


def list_cartridge_stock(session: Session, search: str | None = None) -> list[CartridgeStock]:
    statement = select(CartridgeStock).where(CartridgeStock.is_active == True)  # noqa: E712
    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(
            CartridgeStock.cartridge_name.ilike(pattern)
            | CartridgeStock.compatible_printer_models.ilike(pattern)
            | CartridgeStock.toner_color.ilike(pattern)
        )
    return session.exec(statement.order_by(CartridgeStock.cartridge_name)).all()


def get_cartridge_stock_or_raise(session: Session, stock_id: uuid.UUID) -> CartridgeStock:
    row = session.get(CartridgeStock, stock_id)
    if not row:
        raise CartridgeStockMissingError("Cartridge stock item not found")
    return row


def list_cartridge_movements(session: Session, stock_id: uuid.UUID, limit: int = 50) -> list[CartridgeStockMovement]:
    get_cartridge_stock_or_raise(session, stock_id)
    return session.exec(
        select(CartridgeStockMovement)
        .where(CartridgeStockMovement.stock_id == stock_id)
        .order_by(CartridgeStockMovement.created_at.desc())
        .limit(limit)
    ).all()


def update_cartridge_stock(
    session: Session,
    stock_id: uuid.UUID,
    payload: CartridgeStockUpdate,
    *,
    actor: str | None = None,
) -> CartridgeStock:
    row = get_cartridge_stock_or_raise(session, stock_id)
    now = datetime.now(UTC)
    data = payload.model_dump(exclude_unset=True)

    if "quantity_on_hand" in data and data["quantity_on_hand"] is not None:
        previous = row.quantity_on_hand
        row.quantity_on_hand = data["quantity_on_hand"]
        delta = row.quantity_on_hand - previous
        if delta:
            session.add(
                CartridgeStockMovement(
                    stock_id=row.id,
                    delta=delta,
                    reason="adjust",
                    note=payload.note,
                    created_by=actor,
                )
            )
    if "minimum_stock" in data and data["minimum_stock"] is not None:
        row.minimum_stock = data["minimum_stock"]

    row.updated_at = now
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def issue_cartridge_stock(
    session: Session,
    stock_id: uuid.UUID,
    payload: CartridgeIssueRequest,
    *,
    actor: str | None = None,
) -> CartridgeStock:
    row = get_cartridge_stock_or_raise(session, stock_id)
    if row.quantity_on_hand < payload.quantity:
        raise CartridgeStockQuantityError("Not enough cartridges on stock")
    row.quantity_on_hand -= payload.quantity
    row.updated_at = datetime.now(UTC)
    session.add(row)
    session.add(
        CartridgeStockMovement(
            stock_id=row.id,
            delta=-payload.quantity,
            reason="issue",
            note=payload.note,
            created_by=actor,
        )
    )
    session.commit()
    session.refresh(row)
    return row
