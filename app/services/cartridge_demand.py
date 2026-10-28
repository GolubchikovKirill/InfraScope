"""How many cartridges of each kind the fleet will need soon, against the stock.

Built on the toner forecast (app.ml.toner): for every printer colour with a
forecast, a cartridge is needed when the current one runs out, and again every
cartridge lifetime after that (100 % / the printer's daily rate) while still
inside the horizon - so a busy printer can need two in a month. Summed per
cartridge model and set against what is on the shelf and the minimum to keep:

    to_order = max(0, needed + minimum_stock - on_hand)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from sqlmodel import Session, select

from app.domains.inventory.models import CartridgeStock
from app.domains.ml.models import MLTonerPrediction

#: A forecast further out than its band can't be ordered against with any
#: confidence; and an idle printer's "lifetime" can run to years.
MAX_LIFETIME_DAYS = 365.0


@dataclass
class CartridgeDemand:
    cartridge_name: str
    toner_color: str | None
    needed: int = 0
    printers: set[str] = field(default_factory=set)
    next_due_days: float | None = None
    stock_id: str | None = None
    on_hand: int | None = None
    minimum_stock: int = 0

    @property
    def to_order(self) -> int:
        if self.on_hand is None:
            return self.needed
        return max(0, self.needed + self.minimum_stock - self.on_hand)


def _key(name: str) -> str:
    return " ".join(name.split()).lower()


def replacements_within(days_left: float, daily_rate: float | None, horizon_days: float) -> int:
    """Cartridges one printer colour will go through in the horizon."""
    if days_left > horizon_days:
        return 0
    if not daily_rate or daily_rate <= 0:
        return 1
    lifetime = min(100.0 / daily_rate, MAX_LIFETIME_DAYS)
    return 1 + math.floor((horizon_days - days_left) / lifetime)


def forecast_cartridge_demand(session: Session, *, horizon_days: int = 30) -> list[CartridgeDemand]:
    stock_by_key = {
        _key(row.cartridge_name): row
        for row in session.exec(select(CartridgeStock).where(CartridgeStock.is_active == True)).all()  # noqa: E712
    }
    demand: dict[str, CartridgeDemand] = {}
    for prediction in session.exec(select(MLTonerPrediction)).all():
        if not prediction.toner_model or prediction.days_to_replacement is None:
            continue
        key = _key(prediction.toner_model)
        item = demand.get(key)
        if item is None:
            stock = stock_by_key.get(key)
            item = demand[key] = CartridgeDemand(
                cartridge_name=stock.cartridge_name if stock else " ".join(prediction.toner_model.split()),
                toner_color=(stock.toner_color if stock else None) or prediction.toner_color,
                stock_id=str(stock.id) if stock else None,
                on_hand=stock.quantity_on_hand if stock else None,
                minimum_stock=stock.minimum_stock if stock else 0,
            )
        item.needed += replacements_within(prediction.days_to_replacement, prediction.daily_rate, horizon_days)
        if prediction.printer_name:
            item.printers.add(prediction.printer_name)
        if item.next_due_days is None or prediction.days_to_replacement < item.next_due_days:
            item.next_due_days = prediction.days_to_replacement
    return sorted(
        demand.values(),
        key=lambda d: (-d.to_order, d.next_due_days if d.next_due_days is not None else math.inf, d.cartridge_name),
    )
