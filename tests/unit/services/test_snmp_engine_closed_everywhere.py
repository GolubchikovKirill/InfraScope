"""Structural guard: every SnmpEngine() must be closed by the function that
creates it.

pysnmp's SnmpEngine opens a UDP socket lazily and never closes it on its
own. The first round of fixes closed the 6 call sites under
app/services/snmp/ and app/services/switches/ - but missed 4 more in
device_poll.py, discovery.py and scanner.py, because the search was scoped
to those two directories instead of the whole app. The leak kept running in
polling-service (~1000 UDP sockets in 20h) until it was spotted again by
hand.

Per-call-site unit tests can't catch that: a call site nobody remembered to
test is exactly the one that leaks. This walks the AST of the entire app
package instead, so any *new* call site added later fails this test unless
it closes its engine too.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[3] / "app"


def _creates_snmp_engine(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == "SnmpEngine":
            return True
    return False


def _closes_dispatcher(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr in ("close_dispatcher", "closeDispatcher")
        ):
            return True
    return False


def _functions_creating_engines() -> list[tuple[str, str, int, bool]]:
    """(file, function, lineno, closes_dispatcher) for every function that
    instantiates an SnmpEngine."""
    found: list[tuple[str, str, int, bool]] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # Only the innermost function that actually calls SnmpEngine():
            # an outer function containing a nested one would otherwise be
            # reported too, and its own close lives in the nested scope.
            nested = [
                n
                for n in ast.walk(node)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n is not node
            ]
            direct = _creates_snmp_engine(node) and not any(_creates_snmp_engine(n) for n in nested)
            if direct:
                # as_posix so the expected-paths assertion below matches on
                # Windows dev machines too, not just the Linux test image.
                rel = path.relative_to(APP_ROOT.parent).as_posix()
                found.append((rel, node.name, node.lineno, _closes_dispatcher(node)))
    return found


def test_every_snmp_engine_is_closed_by_its_creator():
    offenders = [(f, fn, line) for f, fn, line, closed in _functions_creating_engines() if not closed]
    assert not offenders, (
        "These functions create an SnmpEngine but never call close_dispatcher() - "
        "each one leaks a UDP socket per invocation:\n"
        + "\n".join(f"  {f}:{line} in {fn}()" for f, fn, line in offenders)
    )


def test_the_guard_actually_finds_the_known_call_sites():
    """Protects the test above from silently passing because the AST walk
    stopped matching anything (e.g. after a refactor to a different
    construction helper)."""
    found = _functions_creating_engines()
    files = {f for f, _fn, _line, _closed in found}

    assert len(found) >= 10, f"expected at least 10 SnmpEngine call sites, found {len(found)}"
    for expected in (
        "app/services/device_poll.py",
        "app/services/discovery.py",
        "app/services/scanner.py",
        "app/services/snmp/mac.py",
        "app/services/snmp/poller.py",
        "app/services/switches/snmp_provider.py",
    ):
        assert expected in files, f"{expected} no longer appears to create an SnmpEngine"
