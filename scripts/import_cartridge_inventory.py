from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlmodel import Session

from app.core.db import engine
from app.services.cartridge_inventory import CartridgeInventoryDocument, reconcile_cartridge_inventory


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a verified cartridge inventory snapshot")
    parser.add_argument("inventory_json", type=Path)
    parser.add_argument("--apply", action="store_true", help="Commit changes; default is a rollback-only preview")
    parser.add_argument("--keep-missing", action="store_true", help="Do not deactivate stock absent from the snapshot")
    parser.add_argument("--actor", default="inventory-import")
    args = parser.parse_args()

    document = CartridgeInventoryDocument.model_validate_json(args.inventory_json.read_text(encoding="utf-8"))
    with Session(engine) as session:
        result = reconcile_cartridge_inventory(
            session,
            document,
            actor=args.actor,
            apply=args.apply,
            deactivate_missing=not args.keep_missing,
        )
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
