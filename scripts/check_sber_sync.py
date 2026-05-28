from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlmodel import Session, select

from app.core.db import engine
from app.models import CashRegister


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/check_sber_sync.py /path/to/seed.json")
        return 2

    seed_path = Path(sys.argv[1])
    if not seed_path.exists():
        print(f"Seed file not found: {seed_path}")
        return 2

    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    by_host = {(row.get("hostname") or "").strip(): row for row in seed if (row.get("hostname") or "").strip()}
    by_kkm = {(row.get("kkm_number") or "").strip(): row for row in seed if (row.get("kkm_number") or "").strip()}

    mismatches: list[tuple[str, str, str, str]] = []
    missing_in_seed = 0

    with Session(engine) as session:
        rows = session.exec(select(CashRegister)).all()
        for db in rows:
            src = by_host.get((db.hostname or "").strip()) or by_kkm.get((db.kkm_number or "").strip())
            if not src:
                missing_in_seed += 1
                continue

            src_sber = (src.get("terminal_id_sber") or "").strip()
            db_sber = (db.terminal_id_sber or "").strip()
            if src_sber != db_sber:
                mismatches.append((db.kkm_number, db.hostname, src_sber, db_sber))

    print(f"rows_total={len(rows)} missing_in_seed={missing_in_seed} sber_mismatch={len(mismatches)}")
    for row in mismatches[:20]:
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
