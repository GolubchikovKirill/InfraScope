from __future__ import annotations

from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    descriptors = sorted((repo_root / "services").glob("*/service.yaml"))
    names: list[str] = []
    for descriptor in descriptors:
        compose_name = ""
        for raw_line in descriptor.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line.startswith("compose_service:"):
                compose_name = line.split(":", 1)[1].strip().strip("'\"")
                break
        if compose_name:
            names.append(compose_name)

    # Core infra services are always checked explicitly.
    names.extend(["kafka", "kafka-ui", "jaeger"])
    unique = []
    seen = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        unique.append(name)
    print(" ".join(unique))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
