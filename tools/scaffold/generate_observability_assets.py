from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


def _load_descriptors(services_dir: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(services_dir.glob("*/service.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(payload, dict):
            items.append(payload)
    return items


def _build_prometheus_targets(descriptors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for item in descriptors:
        compose_service = str(item.get("compose_service", "")).strip()
        runtime = item.get("runtime") or {}
        observability = item.get("observability") or {}
        port = runtime.get("port")
        job = str(observability.get("prometheus_job", "")).strip()
        metrics_path = str(observability.get("metrics_path", "")).strip()
        if not compose_service or not job or not port or not metrics_path:
            continue
        targets.append(
            {
                "targets": [f"{compose_service}:{int(port)}"],
                "labels": {
                    "job": f"infrascope-{job}",
                    "service_name": str(item.get("name", compose_service)),
                    "__metrics_path__": metrics_path,
                },
            }
        )
    return targets


def _build_generated_alerts(descriptors: list[dict[str, Any]]) -> dict[str, Any]:
    rules: list[dict[str, Any]] = []
    for item in descriptors:
        observability = item.get("observability") or {}
        job = str(observability.get("prometheus_job", "")).strip()
        if not job:
            continue
        service_id = str(item.get("name", job)).replace("-", "_")
        display = str(item.get("display_name", item.get("name", job)))
        rules.append(
            {
                "alert": f"InfraScope{service_id.title().replace('_', '')}Down",
                "expr": f'max_over_time(up{{job="infrascope-{job}"}}[2m]) == 0',
                "for": "2m",
                "labels": {"severity": "critical"},
                "annotations": {
                    "summary": f"{display} недоступен",
                    "description": f"Prometheus не может собрать метрики {display} более 2 минут.",
                },
            }
        )
    return {"groups": [{"name": "infrascope-generated-service-alerts", "rules": rules}]}


def _build_dashboard(descriptors: list[dict[str, Any]]) -> dict[str, Any]:
    panels: list[dict[str, Any]] = []
    y = 0
    panel_id = 1
    for item in descriptors:
        observability = item.get("observability") or {}
        job = str(observability.get("prometheus_job", "")).strip()
        if not job:
            continue
        display = str(item.get("display_name", item.get("name", job)))
        panels.append(
            {
                "id": panel_id,
                "type": "stat",
                "title": f"{display} up",
                "gridPos": {"h": 4, "w": 6, "x": ((panel_id - 1) % 4) * 6, "y": y},
                "targets": [{"expr": f'avg(up{{job="infrascope-{job}"}})', "refId": "A"}],
                "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
            }
        )
        panel_id += 1
        if (panel_id - 1) % 4 == 0:
            y += 4
    return {
        "id": None,
        "uid": "infrascope-services-catalog",
        "title": "infrascope-services-catalog",
        "schemaVersion": 39,
        "version": 1,
        "refresh": "30s",
        "tags": ["infrascope", "services", "generated"],
        "timezone": "browser",
        "editable": True,
        "panels": panels,
        "templating": {"list": []},
        "time": {"from": "now-6h", "to": "now"},
    }


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    descriptors = _load_descriptors(repo_root / "services")

    targets_path = repo_root / "monitoring" / "prometheus" / "rules" / "service-targets.json"
    targets_path.parent.mkdir(parents=True, exist_ok=True)
    targets_path.write_text(
        json.dumps(_build_prometheus_targets(descriptors), ensure_ascii=True, indent=2), encoding="utf-8"
    )

    alerts_path = repo_root / "monitoring" / "prometheus" / "rules" / "generated-service-alerts.yml"
    alerts_path.write_text(yaml.safe_dump(_build_generated_alerts(descriptors), sort_keys=False), encoding="utf-8")

    dashboard_path = repo_root / "monitoring" / "grafana" / "dashboards" / "infrascope-services-catalog.json"
    dashboard_path.write_text(json.dumps(_build_dashboard(descriptors), ensure_ascii=True, indent=2), encoding="utf-8")

    print("Generated observability assets:")
    print(f" - {targets_path.relative_to(repo_root)}")
    print(f" - {alerts_path.relative_to(repo_root)}")
    print(f" - {dashboard_path.relative_to(repo_root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
