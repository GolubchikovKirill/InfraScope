from types import SimpleNamespace

from app.api.routes import tasks as task_routes


def test_enqueue_scan_network_requires_superuser(client, admin_token: str, monkeypatch):
    monkeypatch.setattr(
        task_routes,
        "scan_network_task",
        SimpleNamespace(delay=lambda *_args, **_kwargs: SimpleNamespace(id="t-scan", state="PENDING")),
    )
    response = client.post(
        "/api/v1/tasks/scan-network",
        json={"subnet": "10.10.10.0/24", "ports": "9100,631"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json()["task_id"] == "t-scan"


def test_enqueue_poll_printers(client, user_token: str, monkeypatch):
    monkeypatch.setattr(
        task_routes,
        "poll_all_printers_task",
        SimpleNamespace(delay=lambda *_args, **_kwargs: SimpleNamespace(id="t-print", state="PENDING")),
    )
    response = client.post(
        "/api/v1/tasks/poll-printers",
        json={"printer_type": "laser"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 200
    assert response.json()["operation"] == "poll_all_printers"


def test_get_task_status_success(client, user_token: str, monkeypatch):
    class _DummyResult:
        state = "SUCCESS"
        result = {"ok": True}

        def ready(self):
            return True

        def successful(self):
            return True

        def failed(self):
            return False

    monkeypatch.setattr(task_routes, "AsyncResult", lambda *_args, **_kwargs: _DummyResult())
    response = client.get(
        "/api/v1/tasks/task-123",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 200
    assert response.json()["result"]["ok"] is True


def test_get_task_status_failure(client, user_token: str, monkeypatch):
    class _DummyResult:
        state = "FAILURE"
        result = RuntimeError("boom")

        def ready(self):
            return True

        def successful(self):
            return False

        def failed(self):
            return True

    monkeypatch.setattr(task_routes, "AsyncResult", lambda *_args, **_kwargs: _DummyResult())
    response = client.get(
        "/api/v1/tasks/task-err",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 200
    assert "boom" in response.json()["error"]


def test_get_task_status_revoked(client, user_token: str, monkeypatch):
    class _DummyResult:
        state = "REVOKED"
        result = None

        def ready(self):
            return True

        def successful(self):
            return False

        def failed(self):
            return False

    monkeypatch.setattr(task_routes, "AsyncResult", lambda *_args, **_kwargs: _DummyResult())
    response = client.get(
        "/api/v1/tasks/task-revoked",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 410


def test_enqueue_ml_run_cycle_requires_superuser(client, admin_token: str, monkeypatch):
    monkeypatch.setattr(
        task_routes,
        "ml_run_cycle_task",
        SimpleNamespace(delay=lambda *_args, **_kwargs: SimpleNamespace(id="t-ml", state="PENDING")),
    )
    response = client.post(
        "/api/v1/tasks/ml-run-cycle",
        json={"force": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json()["operation"] == "ml_run_cycle"
