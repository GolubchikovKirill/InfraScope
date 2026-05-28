from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    schema_path = repo_root / "tools/scaffold/service.schema.json"
    services_dir = repo_root / "services"
    if not schema_path.exists():
        print(f"Schema file is missing: {schema_path}")
        return 1
    if not services_dir.exists():
        print(f"Services directory is missing: {services_dir}")
        return 1

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    descriptor_paths = sorted(services_dir.glob("*/service.yaml"))
    if not descriptor_paths:
        print("No service descriptors found in services/*/service.yaml")
        return 1

    errors: list[str] = []
    seen_names: set[str] = set()
    for descriptor_path in descriptor_paths:
        data = yaml.safe_load(descriptor_path.read_text(encoding="utf-8")) or {}
        for err in validator.iter_errors(data):
            path = ".".join(str(p) for p in err.path) or "<root>"
            errors.append(f"{descriptor_path}: {path}: {err.message}")
        name = str(data.get("name", "")).strip()
        if not name:
            errors.append(f"{descriptor_path}: name is required")
        elif name in seen_names:
            errors.append(f"{descriptor_path}: duplicate service name '{name}'")
        else:
            seen_names.add(name)

    if errors:
        print("Service descriptor validation failed:")
        for line in errors:
            print(f" - {line}")
        return 1

    print(f"Validated {len(descriptor_paths)} service descriptors.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
