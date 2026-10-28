"""Guards for what prestart.sh runs on every deploy - `alembic upgrade head`.

Both failures here took production down once (October 2026): a new migration
reused an existing revision id, which alembic reports as a cycle and refuses
to upgrade at all; and the async driver alembic/env.py connects through was
dropped from the dependencies because nothing in app/ imports it.
"""

from __future__ import annotations

import ast
import importlib
from collections import Counter
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[3]


def _declared_revisions() -> list[str]:
    revisions = []
    for path in (ROOT / "alembic" / "versions").glob("*.py"):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.AnnAssign) and node.value is not None:
                target, value = node.target, node.value
            elif isinstance(node, ast.Assign):
                target, value = node.targets[0], node.value
            else:
                continue
            if isinstance(target, ast.Name) and target.id == "revision":
                revisions.append(ast.literal_eval(value))
    return revisions


def test_every_revision_id_is_unique() -> None:
    duplicates = [rev for rev, n in Counter(_declared_revisions()).items() if n > 1]
    assert duplicates == []


def test_the_history_is_one_line_with_a_single_head() -> None:
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert len(script.get_heads()) == 1
    # Walking the whole graph is what raises on a cycle
    assert len(list(script.walk_revisions())) == len(_declared_revisions())


def test_the_migration_driver_is_installed() -> None:
    # alembic/env.py runs on settings.ASYNC_DATABASE_URI (postgresql+asyncpg)
    from app.core.config import settings

    assert settings.ASYNC_DATABASE_URI.startswith("postgresql+asyncpg://")
    importlib.import_module("asyncpg")
    importlib.import_module("greenlet")
