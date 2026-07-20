from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import Session, select

from app.core.db import engine
from app.models import CashRegister
from app.services.cache import invalidate_entity_cache


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

            existing = session.exec(select(CashRegister).where(CashRegister.kkm_number == kkm_number)).first()
            if not existing:
                existing = session.exec(select(CashRegister).where(CashRegister.hostname == hostname)).first()

            data = {
                "source_order": row.get("source_order"),
                "location_zone": _norm(row.get("location_zone")),
                "kkm_number": kkm_number,
                "store_number": _norm(row.get("store_number")),
                "store_code": _norm(row.get("store_code")),
                "sber_store_code": _norm(row.get("sber_store_code")),
                "serial_number": _norm(row.get("serial_number")),
                "inventory_number": _norm(row.get("inventory_number")),
                "terminal_id_rs": _norm(row.get("terminal_id_rs")),
                "terminal_id_sber": _norm(row.get("terminal_id_sber")),
                "windows_version": _norm(row.get("windows_version")),
                "kkm_type": _norm(row.get("kkm_type")) or "retail",
                "rosenzweig_number": _norm(row.get("rosenzweig_number")),
                "cash_number": _norm(row.get("cash_number")),
                "hostname": hostname,
                "netsupport_target": _norm(row.get("netsupport_target")) or hostname,
                "second_screen": _norm(row.get("second_screen")),
                "piot_status": _norm(row.get("piot_status")),
                "cash_drawer": _norm(row.get("cash_drawer")),
                "terminal_status": _norm(row.get("terminal_status")),
                "comment": _norm(row.get("comment")),
            }

            if existing:
                existing.sqlmodel_update(data)
                existing.updated_at = datetime.now(UTC)
                session.add(existing)
                updated += 1
            else:
                session.add(CashRegister(**data))
                created += 1

        session.commit()

    asyncio.run(invalidate_entity_cache("cash_registers"))
    print(f"created={created} updated={updated} skipped={skipped} total_input={len(payload)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
