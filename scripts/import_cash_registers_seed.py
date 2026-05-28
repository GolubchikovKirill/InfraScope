from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlmodel import Session, select

from app.core.db import engine
from app.models import CashRegister


def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/import_cash_registers_seed.py /path/to/seed.json")
        return 2

    seed_path = Path(sys.argv[1])
    if not seed_path.exists():
        print(f"Seed file not found: {seed_path}")
        return 2

    payload = json.loads(seed_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        print("Seed must be a JSON array")
        return 2

    created = 0
    updated = 0
    skipped = 0

    with Session(engine) as session:
        for row in payload:
            if not isinstance(row, dict):
                skipped += 1
                continue

            hostname = _norm(row.get("hostname"))
            kkm_number = _norm(row.get("kkm_number"))
            if not hostname or not kkm_number:
                skipped += 1
                continue

            existing = session.exec(select(CashRegister).where(CashRegister.hostname == hostname)).first()
            if not existing:
                existing = session.exec(select(CashRegister).where(CashRegister.kkm_number == kkm_number)).first()

            data = {
                "kkm_number": kkm_number,
                "store_number": _norm(row.get("store_number")),
                "store_code": _norm(row.get("store_code")),
                "serial_number": _norm(row.get("serial_number")),
                "inventory_number": _norm(row.get("inventory_number")),
                "terminal_id_rs": _norm(row.get("terminal_id_rs")),
                "terminal_id_sber": _norm(row.get("terminal_id_sber")),
                "windows_version": _norm(row.get("windows_version")),
                "kkm_type": _norm(row.get("kkm_type")) or "retail",
                "cash_number": _norm(row.get("cash_number")),
                "hostname": hostname,
                "comment": _norm(row.get("comment")),
            }

            if existing:
                existing.sqlmodel_update(data)
                session.add(existing)
                updated += 1
            else:
                session.add(CashRegister(**data))
                created += 1

        session.commit()

    print(f"created={created} updated={updated} skipped={skipped} total_input={len(payload)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
