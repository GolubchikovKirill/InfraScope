from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from sqlmodel import Session, select

from app.core.db import engine
from app.models import CashRegister


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _group_key(store_number: str | None, store_code: str | None) -> str:
    number = _clean(store_number)
    if number:
        return f"store_number:{number}"
    code = _clean(store_code)
    return f"store_code:{code}" if code else ""


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/fill_sber_by_store.py /path/to/seed.json")
        return 2

    seed_path = Path(sys.argv[1])
    if not seed_path.exists():
        print(f"Seed file not found: {seed_path}")
        return 2

    data = json.loads(seed_path.read_text(encoding="utf-8"))
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in data:
        key = _group_key(row.get("store_number"), row.get("store_code"))
        if key:
            grouped[key].append(row)

    fill_map: dict[str, str] = {}
    groups_total = len(grouped)
    groups_single_source = 0
    groups_multi_source = 0
    rows_to_fill_seed = 0

    for key, rows in grouped.items():
        unique_vals = sorted({_clean(r.get("terminal_id_sber")) for r in rows if _clean(r.get("terminal_id_sber"))})
        if len(unique_vals) == 1:
            fill_map[key] = unique_vals[0]
            groups_single_source += 1
            rows_to_fill_seed += sum(1 for r in rows if not _clean(r.get("terminal_id_sber")))
        elif len(unique_vals) > 1:
            groups_multi_source += 1

    updated_db_rows = 0
    skipped_no_match = 0
    with Session(engine) as session:
        rows = session.exec(select(CashRegister)).all()
        for db_row in rows:
            key = _group_key(db_row.store_number, db_row.store_code)
            fill_value = fill_map.get(key)
            if not fill_value:
                continue
            if _clean(db_row.terminal_id_sber):
                continue
            db_row.terminal_id_sber = fill_value
            session.add(db_row)
            updated_db_rows += 1
        session.commit()

        # sanity check: rows still empty where a single fill value existed
        for db_row in rows:
            key = _group_key(db_row.store_number, db_row.store_code)
            if key in fill_map and not _clean(db_row.terminal_id_sber):
                skipped_no_match += 1

    print(
        "groups_total="
        f"{groups_total} groups_single_source={groups_single_source} groups_multi_source={groups_multi_source} "
        f"rows_to_fill_seed={rows_to_fill_seed} rows_updated_db={updated_db_rows} unresolved_after_fill={skipped_no_match}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
