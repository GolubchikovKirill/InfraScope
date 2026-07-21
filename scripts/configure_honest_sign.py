from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
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


def read_hostname_map(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        host_text, separator, hostname_text = line.partition("|")
        if not separator:
            raise ValueError(f"Invalid hostname map line {line_number}")
        host = str(ipaddress.IPv4Address(host_text.strip()))
        hostname = hostname_text.strip().rstrip(".")
        labels = hostname.split(".")
        if (
            not hostname
            or len(hostname) > 255
            or any(
                not label
                or len(label) > 63
                or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", label)
                for label in labels
            )
        ):
            raise ValueError(f"Invalid hostname on line {line_number}")
        result[host] = hostname
    return result


def read_targets(path: Path, hostnames: dict[str, str] | None = None) -> list[str]:
    hostname_map = hostnames or {}
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
        suffix = f"|{hostname_map[host]}" if host in hostname_map else ""
        result.append(f"{host}|{label}{suffix}")
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
    parser.add_argument("--hostname-map", type=Path)
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("--allowed-email", default="golubchikovka@regstaer.ru")
    parser.add_argument("--max-concurrency", type=int, default=32)
    args = parser.parse_args()

    if not 1 <= args.max_concurrency <= 32:
        parser.error("--max-concurrency must be between 1 and 32")

    config = read_configuration(args.config)
    hostnames = read_hostname_map(args.hostname_map) if args.hostname_map else {}
    targets = read_targets(args.computers, hostnames)
    update_env(
        args.env,
        {
            "HONEST_SIGN_ALLOWED_EMAILS": args.allowed_email.strip().casefold(),
            "HONEST_SIGN_TARGETS": ",".join(targets),
            "HONEST_SIGN_API_LOGIN": config["login"],
            "HONEST_SIGN_API_PASSWORD": config["password"],
            "HONEST_SIGN_TOKEN": config["token"],
            "HONEST_SIGN_MAX_CONCURRENCY": str(args.max_concurrency),
        },
    )
    matched_hostnames = sum(1 for target in targets if target.count("|") == 2)
    print(
        f"configured_targets={len(targets)} matched_hostnames={matched_hostnames} "
        "allowed_accounts=1"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
