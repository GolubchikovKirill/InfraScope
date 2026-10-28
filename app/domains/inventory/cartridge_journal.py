"""The cartridge replacement journal, filled in by polling.

A swap shows up as one colour's level rising by a refill's worth between two
full polls. Nobody has to record it: the poll that sees the jump writes the
journal row, with how long the outgoing cartridge lasted and how many pages it
printed (measured from the previous swap on the same printer and colour).

Same threshold as the toner forecast's segmentation (app.ml.toner.series), so
the journal and the forecast agree on what a swap is.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlmodel import Session, col, select

from app.domains.inventory.models import CartridgeReplacement, Printer
from app.services.event_log import write_event_log

#: A rise this large between polls is a new cartridge, not measurement noise
REFILL_JUMP = 15

COLORS = ("black", "cyan", "magenta", "yellow")


@dataclass(frozen=True)
class DetectedSwap:
    color: str
    level_before: int
    level_after: int


def _levels(printer: Printer) -> dict[str, int | None]:
    return {
        "black": printer.toner_black,
        "cyan": printer.toner_cyan,
        "magenta": printer.toner_magenta,
        "yellow": printer.toner_yellow,
    }


def _cartridge_name(printer: Printer, color: str) -> str | None:
    return getattr(printer, f"toner_{color}_name")


def detect_swaps(before: dict[str, int | None], after: dict[str, int | None]) -> list[DetectedSwap]:
    """Colours whose level jumped up by a refill. Negative values are status
    codes (-2 unknown, -3 "some left"), not levels, and never count."""
    swaps = []
    for color in COLORS:
        old, new = before.get(color), after.get(color)
        if old is None or new is None or old < 0 or new < 0:
            continue
        if new >= old + REFILL_JUMP:
            swaps.append(DetectedSwap(color, old, new))
    return swaps


def record_swaps(
    session: Session,
    printer: Printer,
    swaps: list[DetectedSwap],
    *,
    page_count: int | None,
    now: datetime | None = None,
) -> list[CartridgeReplacement]:
    now = now or datetime.now(UTC)
    rows = []
    for swap in swaps:
        previous = session.exec(
            select(CartridgeReplacement)
            .where(CartridgeReplacement.printer_id == printer.id, CartridgeReplacement.toner_color == swap.color)
            .order_by(col(CartridgeReplacement.replaced_at).desc())
        ).first()
        lifetime_days = pages_printed = None
        previous_at = None
        if previous is not None:
            previous_at = previous.replaced_at
            if previous_at.tzinfo is None:  # SQLite hands timestamps back naive
                previous_at = previous_at.replace(tzinfo=UTC)
            lifetime_days = (now - previous_at).total_seconds() / 86400.0
            if page_count is not None and previous.page_count is not None and page_count >= previous.page_count:
                pages_printed = page_count - previous.page_count
        row = CartridgeReplacement(
            printer_id=printer.id,
            store_name=printer.store_name,
            printer_model=printer.model,
            toner_color=swap.color,
            cartridge_name=_cartridge_name(printer, swap.color),
            level_before=swap.level_before,
            level_after=swap.level_after,
            page_count=page_count,
            previous_replaced_at=previous_at,
            lifetime_days=lifetime_days,
            pages_printed=pages_printed,
            replaced_at=now,
        )
        session.add(row)
        rows.append(row)
        write_event_log(
            session,
            category="device",
            event_type="cartridge_replaced",
            severity="info",
            device_kind="printer",
            device_name=printer.store_name,
            ip_address=printer.ip_address,
            message=(
                f"Printer '{printer.store_name}': {swap.color} cartridge replaced "
                f"({swap.level_before}% -> {swap.level_after}%)"
                + (f", the old one lasted {lifetime_days:.0f} days" if lifetime_days is not None else "")
            ),
        )
    return rows


def toner_levels(printer: Printer) -> dict[str, int | None]:
    """The printer's current levels by colour - taken before a poll overwrites
    them, to compare against after."""
    return _levels(printer)


@dataclass(frozen=True)
class CartridgeLifeStats:
    cartridge_name: str
    toner_color: str
    replacements: int
    median_lifetime_days: float | None
    median_pages: int | None


def lifetime_stats(rows: list[CartridgeReplacement]) -> list[CartridgeLifeStats]:
    """Median measured life per cartridge model, from swaps whose life is known."""
    grouped: dict[tuple[str, str], list[CartridgeReplacement]] = defaultdict(list)
    for row in rows:
        grouped[((row.cartridge_name or "—").strip(), row.toner_color)].append(row)
    stats = []
    for (name, color), items in grouped.items():
        days = [r.lifetime_days for r in items if r.lifetime_days is not None]
        pages = [r.pages_printed for r in items if r.pages_printed is not None]
        stats.append(
            CartridgeLifeStats(
                cartridge_name=name,
                toner_color=color,
                replacements=len(items),
                median_lifetime_days=statistics.median(days) if days else None,
                median_pages=int(statistics.median(pages)) if pages else None,
            )
        )
    return sorted(stats, key=lambda s: (-s.replacements, s.cartridge_name))
