from __future__ import annotations

import argparse
import ipaddress
import json
import os
import tempfile
import uuid
from pathlib import Path


def read_configuration(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip().casefold()] = value.strip()
    missing = [name for name in ("token", "login", "password") if not values.get(name)]
    if missing:
        raise ValueError(f"Missing configuration values: {', '.join(missing)}")
    uuid.UUID(values["token"])
    return values


def read_targets(path: Path) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    label = "Касса"
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            label = line.lstrip("#").strip() or "Касса"
            continue
        host_text = line.split("#", 1)[0].strip()
        host = str(ipaddress.IPv4Address(host_text))
        if host in seen:
            continue
        seen.add(host)
        result.append(f"{host}|{label}")
    if not result:
        raise ValueError("Computer list is empty")
    return result


def update_env(path: Path, updates: dict[str, str]) -> None:
    existing_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pending = dict(updates)
    output: list[str] = []
    for line in existing_lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0].strip() if "=" in stripped and not stripped.startswith("#") else ""
        if key in pending:
            output.append(f"{key}={json.dumps(pending.pop(key), ensure_ascii=False)}")
        else:
            output.append(line)
    if pending:
        if output and output[-1]:
            output.append("")
        output.append("# Honest Sign Local Module")
        output.extend(f"{key}={json.dumps(value, ensure_ascii=False)}" for key, value in pending.items())

    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as temporary:
            temporary.write("\n".join(output) + "\n")
        try:
            os.chmod(temporary_name, 0o600)
        except OSError:
            pass
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure Honest Sign Local Module integration")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--computers", type=Path, required=True)
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("--allowed-email", default="golubchikovka@regstaer.ru")
    args = parser.parse_args()

    config = read_configuration(args.config)
    targets = read_targets(args.computers)
    update_env(
        args.env,
        {
            "HONEST_SIGN_ALLOWED_EMAILS": args.allowed_email.strip().casefold(),
            "HONEST_SIGN_TARGETS": ",".join(targets),
            "HONEST_SIGN_API_LOGIN": config["login"],
            "HONEST_SIGN_API_PASSWORD": config["password"],
            "HONEST_SIGN_TOKEN": config["token"],
        },
    )
    print(f"configured_targets={len(targets)} allowed_accounts=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
