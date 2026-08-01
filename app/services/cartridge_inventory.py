from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from sqlmodel import Session, select

from app.domains.inventory.models import CartridgeStock, CartridgeStockMovement


class CartridgeInventoryItem(BaseModel):
    cartridge_name: str = Field(min_length=1, max_length=128)
    toner_color: Literal["black", "cyan", "magenta", "yellow"] | None = None
    quantity_on_hand: int = Field(ge=0)
    compatible_printer_models: str = Field(default="", max_length=1024)
    source_row: int | None = Field(default=None, ge=1)


class CartridgeInventoryDocument(BaseModel):
    source_file: str = Field(min_length=1, max_length=255)
    inventory_date: date
    position_count: int = Field(ge=0)
    quantity_total: int = Field(ge=0)
    items: list[CartridgeInventoryItem]

    @model_validator(mode="after")
    def validate_totals_and_unique_names(self) -> CartridgeInventoryDocument:
        names = [item.cartridge_name for item in self.items]
        if len(names) != len(set(names)):
            raise ValueError("cartridge_name values must be unique")
        if self.position_count != len(self.items):
            raise ValueError("position_count does not match items")
        if self.quantity_total != sum(item.quantity_on_hand for item in self.items):
            raise ValueError("quantity_total does not match items")
        return self


class CartridgeInventoryImportResult(BaseModel):
    applied: bool
    created: int
    updated: int
    deactivated: int
    movements: int
    active_positions: int
    active_quantity: int


def _movement_note(document: CartridgeInventoryDocument, *, source_row: int | None = None) -> str:
    note = f"Инвентаризация {document.inventory_date.isoformat()}; {document.source_file}"
    if source_row is not None:
        note = f"{note}; строка {source_row}"
    return note[:512]


def reconcile_cartridge_inventory(
    session: Session,
    document: CartridgeInventoryDocument,
    *,
    actor: str | None,
    apply: bool,
    deactivate_missing: bool = True,
) -> CartridgeInventoryImportResult:
    now = datetime.now(UTC)
    existing_rows = session.exec(select(CartridgeStock)).all()
    existing_by_name = {row.cartridge_name: row for row in existing_rows}
    desired_names = {item.cartridge_name for item in document.items}

    created = 0
    updated = 0
    deactivated = 0
    movement_count = 0

    for item in document.items:
        row = existing_by_name.get(item.cartridge_name)
        if row is None:
            row = CartridgeStock(cartridge_name=item.cartridge_name)
            existing_by_name[item.cartridge_name] = row
            created += 1
        else:
            updated += 1

        previous_quantity = row.quantity_on_hand
        row.toner_color = item.toner_color
        row.compatible_printer_models = item.compatible_printer_models
        row.quantity_on_hand = item.quantity_on_hand
        row.is_active = True
        row.last_synced_at = now
        row.updated_at = now
        session.add(row)

        delta = item.quantity_on_hand - previous_quantity
        if delta:
            session.add(
                CartridgeStockMovement(
                    stock_id=row.id,
                    delta=delta,
                    reason="inventory",
                    note=_movement_note(document, source_row=item.source_row),
                    created_by=actor,
                )
            )
            movement_count += 1

    if deactivate_missing:
        for row in existing_rows:
            if not row.is_active or row.cartridge_name in desired_names:
                continue
            previous_quantity = row.quantity_on_hand
            row.quantity_on_hand = 0
            row.is_active = False
            row.updated_at = now
            session.add(row)
            deactivated += 1
            if previous_quantity:
                session.add(
                    CartridgeStockMovement(
                        stock_id=row.id,
                        delta=-previous_quantity,
                        reason="inventory",
                        note=_movement_note(document),
                        created_by=actor,
                    )
                )
                movement_count += 1

    session.flush()
    active_rows = [row for row in existing_by_name.values() if row.is_active]
    result = CartridgeInventoryImportResult(
        applied=apply,
        created=created,
        updated=updated,
        deactivated=deactivated,
        movements=movement_count,
        active_positions=len(active_rows),
        active_quantity=sum(row.quantity_on_hand for row in active_rows),
    )
    if apply:
        session.commit()
    else:
        session.rollback()
    return result
