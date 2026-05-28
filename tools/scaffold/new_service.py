from __future__ import annotations

import argparse
import subprocess
import textwrap
from pathlib import Path

import yaml


def _service_descriptor(name: str, port: int) -> dict:
    return {
        "name": name,
        "display_name": name.replace("-", " ").title(),
        "kind": "service",
        "owner": "platform-team",
        "compose_service": name,
        "runtime": {
            "language": "python",
            "module": f"services.{name.replace('-', '_')}.src.main:app",
            "port": port,
        },
        "observability": {
            "prometheus_job": name,
            "health_path": "/health",
            "metrics_path": "/metrics",
            "service_map_enabled": True,
        },
        "dependencies": [
            {"target": "backend", "transport": "http", "operation": "internal-api"},
        ],
        "k8s": {
            "enabled": True,
            "replicas": 1,
            "resources_profile": "small",
            "ingress_enabled": False,
        },
        "ci": {
            "lint_command": f"uv run ruff check services/{name}",
            "test_command": f"uv run pytest services/{name}/tests -q",
            "build_context": ".",
            "dockerfile": "Dockerfile",
        },
    }


def _catalog_node(name: str) -> dict:
    return {
        "id": name,
        "label": name.replace("-", " ").title(),
        "kind": "service",
        "prometheus_job": name,
        "service_map_enabled": True,
    }


def _catalog_edge(name: str) -> dict:
    return {
        "source": "backend",
        "target": name,
        "transport": "http",
        "operation": "internal proxy",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Scaffold a new plug-and-play service.")
    parser.add_argument("--name", required=True, help="Service name (kebab-case).")
    parser.add_argument("--port", required=True, type=int, help="Service port.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    service_dir = repo_root / "services" / args.name
    if service_dir.exists():
        raise SystemExit(f"Service already exists: {service_dir}")

    src_dir = service_dir / "src"
    tests_dir = service_dir / "tests"
    src_dir.mkdir(parents=True, exist_ok=False)
    tests_dir.mkdir(parents=True, exist_ok=False)

    (src_dir / "__init__.py").write_text("", encoding="utf-8")
    (tests_dir / "__init__.py").write_text("", encoding="utf-8")
    (src_dir / "main.py").write_text(
        textwrap.dedent(
            """\
            from fastapi import FastAPI

            app = FastAPI(title="Service")


            @app.get("/health")
            def health() -> dict[str, str]:
                return {"status": "ok"}
            """
        ),
        encoding="utf-8",
    )
    (tests_dir / "test_health.py").write_text(
        textwrap.dedent(
            """\
            from fastapi.testclient import TestClient

            from services.sample.src.main import app


            def test_health():
                client = TestClient(app)
                response = client.get("/health")
                assert response.status_code == 200
            """
        ).replace("sample", args.name.replace("-", "_")),
        encoding="utf-8",
    )
    (service_dir / "README.md").write_text(
        f"# {args.name}\n\nScaffolded service.\n",
        encoding="utf-8",
    )
    (service_dir / "service.yaml").write_text(
        yaml.safe_dump(_service_descriptor(args.name, args.port), sort_keys=False),
        encoding="utf-8",
    )

    catalog_path = repo_root / "services" / "catalog.yaml"
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8")) if catalog_path.exists() else {}
    catalog.setdefault("nodes", [])
    catalog.setdefault("edges", [])
    catalog["nodes"].append(_catalog_node(args.name))
    catalog["edges"].append(_catalog_edge(args.name))
    catalog_path.write_text(yaml.safe_dump(catalog, sort_keys=False), encoding="utf-8")

    helm_values = repo_root / "infra/helm/services" / f"{args.name}.values.yaml"
    helm_values.parent.mkdir(parents=True, exist_ok=True)
    helm_values.write_text(
        textwrap.dedent(
            f"""\
            service:
              name: {args.name}
              port: {args.port}
              healthPath: /health
              metricsPath: /metrics
            image:
              repository: ghcr.io/your-org/{args.name}
              tag: latest
            """
        ),
        encoding="utf-8",
    )
    print(f"Scaffolded service: {args.name}")
    generator = repo_root / "tools" / "scaffold" / "generate_observability_assets.py"
    subprocess.run(
        ["python", str(generator)],
        check=True,
        cwd=repo_root,
    )
    print("Next steps:")
    print(f" - implement service code in {service_dir}")
    print(f" - adjust tests in {tests_dir}")
    print(" - run: uv run python tools/scaffold/validate_service_descriptors.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
