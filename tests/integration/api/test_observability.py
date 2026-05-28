from datetime import UTC, datetime

from app.api.routes import observability as observability_routes


def test_get_service_map_requires_auth(client):
    response = client.get("/api/v1/observability/service-map")
    assert response.status_code in (401, 403)


def test_get_service_map(client, admin_token, monkeypatch):
    def _fake_build_service_flow_map(_session):
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "nodes": [
                {
                    "id": "backend",
                    "label": "API Gateway",
                    "kind": "gateway",
                    "status": "healthy",
                    "req_rate": 1.2,
                    "error_rate": 0.0,
                    "p95_latency_ms": 25.0,
                    "last_seen": datetime.now(UTC).isoformat(),
                    "links": [{"label": "Jaeger traces", "url": "http://127.0.0.1:16686"}],
                }
            ],
            "edges": [
                {
                    "source": "frontend",
                    "target": "backend",
                    "transport": "http",
                    "operation": "ui requests",
                    "status": "healthy",
                    "req_rate": 1.2,
                    "error_rate": 0.0,
                    "p95_latency_ms": 25.0,
                }
            ],
            "recent_events": [],
        }

    monkeypatch.setattr(observability_routes, "build_service_flow_map", _fake_build_service_flow_map)
    response = client.get("/api/v1/observability/service-map", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 200
    data = response.json()
    assert data["nodes"][0]["id"] == "backend"
    assert data["edges"][0]["source"] == "frontend"


def test_get_service_map_timeseries(client, admin_token, monkeypatch):
    def _fake_build_service_flow_timeseries(**_kwargs):
        return {
            "entity": "service:backend",
            "points": [
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "req_rate": 2.3,
                    "error_rate": 0.1,
                    "p95_latency_ms": 40.0,
                }
            ],
        }

    monkeypatch.setattr(observability_routes, "build_service_flow_timeseries", _fake_build_service_flow_timeseries)
    response = client.get(
        "/api/v1/observability/service-map/timeseries",
        headers={"Authorization": f"Bearer {admin_token}"},
        params={"service": "backend", "minutes": 30, "step_seconds": 15},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["entity"] == "service:backend"
    assert len(data["points"]) == 1
