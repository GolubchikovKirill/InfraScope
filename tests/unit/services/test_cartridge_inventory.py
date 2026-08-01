from sqlmodel import Session, select

from app.domains.inventory.models import CartridgeStock, CartridgeStockMovement
from app.services.cartridge_inventory import CartridgeInventoryDocument, reconcile_cartridge_inventory


def _document() -> CartridgeInventoryDocument:
    return CartridgeInventoryDocument.model_validate(
        {
            "source_file": "inventory.xlsx",
            "inventory_date": "2026-08-01",
            "position_count": 2,
            "quantity_total": 5,
            "items": [
                {
                    "cartridge_name": "Vendor · MODEL-K [K]",
                    "toner_color": "black",
                    "quantity_on_hand": 2,
                    "compatible_printer_models": "Printer A",
                    "source_row": 6,
                },
                {
                    "cartridge_name": "Vendor · MODEL-C [C]",
                    "toner_color": "cyan",
                    "quantity_on_hand": 3,
                    "compatible_printer_models": "Printer A",
                    "source_row": 7,
                },
            ],
        }
    )


def test_inventory_preview_rolls_back(db_session: Session):
    db_session.add(CartridgeStock(cartridge_name="Legacy", quantity_on_hand=4))
    db_session.commit()

    result = reconcile_cartridge_inventory(
        db_session,
        _document(),
        actor="operator@example.com",
        apply=False,
    )

    assert result.applied is False
    assert result.created == 2
    assert result.deactivated == 1
    assert result.active_positions == 2
    assert result.active_quantity == 5
    rows = db_session.exec(select(CartridgeStock)).all()
    assert [(row.cartridge_name, row.quantity_on_hand, row.is_active) for row in rows] == [("Legacy", 4, True)]


def test_inventory_apply_replaces_active_snapshot_and_keeps_history(db_session: Session):
    db_session.add(CartridgeStock(cartridge_name="Legacy", quantity_on_hand=4))
    db_session.commit()

    result = reconcile_cartridge_inventory(
        db_session,
        _document(),
        actor="operator@example.com",
        apply=True,
    )

    assert result.applied is True
    assert result.created == 2
    assert result.deactivated == 1
    assert result.movements == 3
    assert result.active_positions == 2
    assert result.active_quantity == 5

    rows = db_session.exec(select(CartridgeStock).order_by(CartridgeStock.cartridge_name)).all()
    assert [(row.cartridge_name, row.quantity_on_hand, row.is_active) for row in rows] == [
        ("Legacy", 0, False),
        ("Vendor · MODEL-C [C]", 3, True),
        ("Vendor · MODEL-K [K]", 2, True),
    ]
    movements = db_session.exec(select(CartridgeStockMovement)).all()
    assert sorted(movement.delta for movement in movements) == [-4, 2, 3]
    assert {movement.reason for movement in movements} == {"inventory"}
    assert {movement.created_by for movement in movements} == {"operator@example.com"}
