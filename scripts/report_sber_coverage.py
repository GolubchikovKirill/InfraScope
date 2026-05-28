from __future__ import annotations

from collections import defaultdict

from sqlmodel import Session, select

from app.core.db import engine
from app.models import CashRegister


def _clean(v: str | None) -> str:
    return (v or "").strip()


def main() -> int:
    with Session(engine) as session:
        rows = session.exec(select(CashRegister).order_by(CashRegister.store_number, CashRegister.kkm_number)).all()

    total = len(rows)
    with_sber = sum(1 for r in rows if _clean(r.terminal_id_sber))
    without_sber = total - with_sber

    grouped: dict[tuple[str, str], list[CashRegister]] = defaultdict(list)
    for row in rows:
        grouped[(_clean(row.store_number), _clean(row.store_code))].append(row)

    print(f"total={total} with_sber={with_sber} without_sber={without_sber} groups={len(grouped)}")
    for key in sorted(grouped.keys())[:8]:
        vals = sorted({_clean(x.terminal_id_sber) for x in grouped[key] if _clean(x.terminal_id_sber)})
        print(f"group={key} rows={len(grouped[key])} sber_values={vals}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
