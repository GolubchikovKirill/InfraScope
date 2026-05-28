from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_background_processes_do_not_import_api_routes_directly() -> None:
    """Background entrypoints should call services, not HTTP route modules."""
    worker_tasks = _read("app/worker/tasks.py")
    polling_main = _read("app/polling_service/main.py")

    assert "from app.api.routes import" not in worker_tasks
    assert "from app.api.routes import" not in polling_main


def test_discovery_does_not_import_private_scanner_helpers() -> None:
    discovery_service = _read("app/services/discovery.py")

    assert "_parse_arp_table" not in discovery_service


def test_route_modules_do_not_manage_realtime_cache_invalidation_directly() -> None:
    route_dir = ROOT / "app/api/routes"
    route_sources = "\n".join(path.read_text(encoding="utf-8") for path in route_dir.glob("*.py"))

    assert "broadcast_event" not in route_sources


def test_orm_table_models_live_in_domain_packages() -> None:
    model_files = [ROOT / "app/models.py", *sorted((ROOT / "app/domains").glob("*/models.py"))]
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
            if has_table_true and path == ROOT / "app/models.py":
                violations.append(node.name)

    assert violations == []


def test_schema_definitions_live_in_domain_packages() -> None:
    schemas_facade = _read("app/schemas.py")

    assert "class " not in schemas_facade
    assert "from app.domains." in schemas_facade

    operations_schemas = _read("app/domains/operations/schemas.py")
    inventory_schemas = _read("app/domains/inventory/schemas.py")
    assert "class Computer" not in operations_schemas
    assert "class Computer" in inventory_schemas


def test_runtime_code_uses_domain_model_imports() -> None:
    offenders: list[str] = []
    for path in (ROOT / "app").rglob("*.py"):
        if path == ROOT / "app/models.py":
            continue
        source = path.read_text(encoding="utf-8")
        if "from app.models import" in source:
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_runtime_code_uses_domain_schema_imports() -> None:
    offenders: list[str] = []
    for path in (ROOT / "app").rglob("*.py"):
        if path == ROOT / "app/schemas.py":
            continue
        source = path.read_text(encoding="utf-8")
        if "from app.schemas import" in source:
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
