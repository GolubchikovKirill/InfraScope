def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers.get("X-Request-ID")
    assert response.headers.get("X-Process-Time-Ms")


def test_ready_endpoint(client):
    response = client.get("/ready")
    assert response.status_code in (200, 503)
    payload = response.json()
    assert payload["status"] in ("ready", "degraded")
    assert "checks" in payload
    assert {"database", "redis"} <= set(payload["checks"].keys())


def test_validation_error_envelope_contains_request_id(client):
    response = client.post("/api/v1/auth/login", data={})
    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"] == "Validation error"
    assert isinstance(payload.get("errors"), list)
    assert payload.get("request_id")
