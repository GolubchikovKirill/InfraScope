from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_background_processes_do_not_import_api_routes_directly() -> None:
    """Background entrypoints should call services, not HTTP route modules."""
    worker_tasks = _read("app/worker/tasks.py")

    assert "from app.api.routes import" not in worker_tasks


def test_route_modules_do_not_manage_realtime_cache_invalidation_directly() -> None:
    route_dir = ROOT / "app/api/routes"
    route_sources = "\n".join(path.read_text(encoding="utf-8") for path in route_dir.rglob("*.py"))

    assert "broadcast_event" not in route_sources


def test_orm_table_models_live_in_domain_packages() -> None:
    model_files = sorted((ROOT / "app/domains").glob("*/models.py"))
    violations: list[str] = []

    for path in model_files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            has_table_true = any(
                keyword.arg == "table" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True
                for keyword in node.keywords
            )
            if has_table_true and path.parent.name == "app":
                violations.append(node.name)

    assert violations == []
    assert model_files, "domain model modules not found"


def test_schema_definitions_live_in_domain_packages() -> None:
    operations_schemas = _read("app/domains/operations/schemas.py")
    inventory_schemas = "\n".join(
        path.read_text(encoding="utf-8") for path in (ROOT / "app/domains/inventory/schemas").glob("*.py")
    )
    assert "class Computer" not in operations_schemas
    assert "class Computer" in inventory_schemas


_REMOVED_FACADES = ("app/models.py", "app/schemas.py", "app/crud.py")
_FACADE_IMPORTS = (
    "from app.models import",
    "from app.schemas import",
    "from app import crud",
    "from app import models",
    "from app import schemas",
    "import app.models",
    "import app.schemas",
    "import app.crud",
)


def test_compatibility_facades_are_gone() -> None:
    """Models, schemas and user CRUD live in `app/domains/*`; the old flat modules must not return."""
    assert [p for p in _REMOVED_FACADES if (ROOT / p).exists()] == []


def test_nothing_imports_the_removed_facades() -> None:
    offenders: list[str] = []
    for base in ("app", "tests", "alembic"):
        for path in (ROOT / base).rglob("*.py"):
            if path == Path(__file__):
                continue
            source = path.read_text(encoding="utf-8")
            if any(marker in source for marker in _FACADE_IMPORTS):
                offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_printer_polling_flow_does_not_depend_on_printer_routes() -> None:
    orchestrator = _read("app/services/polling_orchestrator.py")
    printer_service = _read("app/domains/inventory/printer_polling.py")

    assert "app.api.routes import printers" not in orchestrator
    assert "app.api.routes.printers" not in printer_service


def test_media_polling_flow_does_not_depend_on_media_routes() -> None:
    orchestrator = _read("app/services/polling_orchestrator.py")
    media_service = _read("app/domains/inventory/media_polling.py")

    assert "app.api.routes import media_players" not in orchestrator
    assert "app.api.routes.media_players" not in media_service


def test_switch_polling_flow_does_not_depend_on_switch_routes() -> None:
    orchestrator = _read("app/services/polling_orchestrator.py")
    switch_service = _read("app/domains/inventory/switch_polling.py")

    assert "app.api.routes import switches" not in orchestrator
    assert "app.api.routes.switches" not in switch_service


def test_cash_register_polling_flow_does_not_depend_on_cash_routes() -> None:
    orchestrator = _read("app/services/polling_orchestrator.py")
    cash_service = _read("app/domains/operations/cash_register_polling.py")

    assert "app.api.routes import cash_registers" not in orchestrator
    assert "app.api.routes.cash_registers" not in cash_service
