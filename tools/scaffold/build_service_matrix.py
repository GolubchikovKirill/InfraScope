from __future__ import annotations

import json
from pathlib import Path

import yaml


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    descriptors = sorted((repo_root / "services").glob("*/service.yaml"))
    include: list[dict[str, str]] = []
    for path in descriptors:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        include.append(
            {
                "name": str(payload.get("name", path.parent.name)),
                "path": str(path.parent.relative_to(repo_root)),
                "lint": str(payload.get("ci", {}).get("lint_command", "echo no-lint")),
                "test": str(payload.get("ci", {}).get("test_command", "echo no-test")),
            }
        )
    print(json.dumps({"include": include}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
