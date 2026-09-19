"""A broad `except Exception` must not swallow the error without a trace.

Each handler has to log, re-raise, record a metric/event, or carry an explicit
`# noqa: BLE001 - <why>` naming the reason it is safe. This is the audit's 3.4
rule turned into a check: silent handlers are how "Event loop is closed" stayed
invisible in production for weeks.
"""

from __future__ import annotations

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"

_BROAD = re.compile(r"^\s*except\s+(Exception|BaseException)\b|^\s*except\s*:")
_TRACE = re.compile(r"logger\.|logging\.|_log\(|\braise\b|record_|write_event_log|\.inc\(|warnings\.warn")


def _handler_body(lines: list[str], start: int) -> str:
    indent = len(lines[start]) - len(lines[start].lstrip())
    body = []
    for line in lines[start + 1 :]:
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        body.append(line)
    return "\n".join(body)


def test_every_broad_except_leaves_a_trace() -> None:
    silent: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        lines = path.read_text(encoding="utf-8").split("\n")
        for i, line in enumerate(lines):
            if not _BROAD.search(line):
                continue
            if "noqa: BLE001" in line and _TRACE.search(_handler_body(lines, i)):
                continue
            if _TRACE.search(_handler_body(lines, i)):
                continue
            silent.append(f"{path.relative_to(APP.parent).as_posix()}:{i + 1}: {line.strip()}")

    assert not silent, "broad except without logging/raise:\n" + "\n".join(silent)
