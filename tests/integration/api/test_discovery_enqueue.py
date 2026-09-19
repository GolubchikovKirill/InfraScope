"""Discovery scans are queued to the worker instead of running in the API process
or in a separate discovery-service container."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.core.redis import get_redis
from app.services import discovery, discovery_jobs, scanner

# (url prefix, kind, progress key, lock key)
CASES = [
    ("/api/v1/scanner", "printers", scanner.SCAN_KEY_PROGRESS, scanner.SCAN_KEY_LOCK),
    ("/api/v1/media-players/discover", "iconbit", "discover:iconbit:progress", "discover:iconbit:lock"),
    ("/api/v1/switches/discover", "switch", "discover:switch:progress", "discover:switch:lock"),
]


def _redis_get(key: str):
    async def _go():
        r = await get_redis()
        return await r.get(key)

    return asyncio.run(_go())


def _redis_set(key: str, value: str):
    async def _go():
        r = await get_redis()
        await r.set(key, value, ex=60)

    asyncio.run(_go())


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    calls: list[tuple] = []
    monkeypatch.setattr(
        discovery_jobs,
        "discovery_scan_task",
        SimpleNamespace(delay=lambda *args: calls.append(args) or SimpleNamespace(id="t-1")),
    )
    return calls


@pytest.mark.parametrize(("prefix", "kind", "progress_key", "lock_key"), CASES)
def test_start_scan_queues_a_task_and_publishes_running_immediately(
    client, admin_token, queued, prefix, kind, progress_key, lock_key
):
    # a finished scan from earlier must not be what the UI sees on its first poll
    _redis_set(progress_key, json.dumps({"status": "done", "scanned": 9, "total": 9, "found": 3, "message": None}))

    response = client.post(
        f"{prefix}/scan" if kind != "printers" else f"{prefix}/scan",
        json={"subnet": "10.10.98.0/30", "ports": "22,80"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert len(queued) == 1
    queued_kind, subnet, ports, known = queued[0]
    assert (queued_kind, subnet, ports) == (kind, "10.10.98.0/30", "22,80")
    assert isinstance(known, list)
    assert json.loads(_redis_get(progress_key))["status"] == "running"


@pytest.mark.parametrize(("prefix", "kind", "progress_key", "lock_key"), CASES)
def test_start_scan_is_rejected_with_409_while_one_is_running(
    client, admin_token, queued, prefix, kind, progress_key, lock_key
):
    _redis_set(lock_key, "some-running-scan")

    response = client.post(
        f"{prefix}/scan",
        json={"subnet": "10.10.98.0/30", "ports": "22,80"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 409
    assert queued == []


@pytest.mark.parametrize(("prefix", "kind", "progress_key", "lock_key"), CASES)
def test_start_scan_reports_503_and_an_error_state_when_the_queue_is_down(
    client, admin_token, monkeypatch, prefix, kind, progress_key, lock_key
):
    def _down(*_a):
        raise ConnectionError("broker unreachable")

    monkeypatch.setattr(discovery_jobs, "discovery_scan_task", SimpleNamespace(delay=_down))

    response = client.post(
        f"{prefix}/scan",
        json={"subnet": "10.10.98.0/30", "ports": "22,80"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 503
    # not left claiming "running" forever
    assert json.loads(_redis_get(progress_key))["status"] == "error"


def test_only_superusers_can_start_a_scan(client, user_token, queued):
    response = client.post(
        "/api/v1/scanner/scan",
        json={"subnet": "10.10.98.0/30", "ports": "22,80"},
        headers={"Authorization": f"Bearer {user_token}"},
    )

    assert response.status_code in (401, 403)
    assert queued == []


def test_status_and_results_are_read_straight_from_redis(client, admin_token):
    _redis_set(
        "discover:switch:progress",
        json.dumps({"status": "done", "scanned": 4, "total": 4, "found": 1, "message": None}),
    )
    _redis_set("discover:switch:results", json.dumps([]))

    status = client.get("/api/v1/switches/discover/status", headers={"Authorization": f"Bearer {admin_token}"})
    results = client.get("/api/v1/switches/discover/results", headers={"Authorization": f"Bearer {admin_token}"})

    assert status.json()["status"] == "done"
    assert results.status_code == 200
    assert results.json()["progress"]["found"] == 1


def test_unknown_kind_is_rejected():
    with pytest.raises(Exception) as excinfo:
        asyncio.run(discovery_jobs.enqueue_scan("cameras", "10.0.0.0/30", "80", []))

    assert getattr(excinfo.value, "status_code", None) == 422


def test_lock_helpers_match_the_keys_the_scans_actually_take():
    """enqueue_scan's 409 check is only as good as these keys agreeing with the
    ones scan_subnet / run_discovery_scan take."""
    assert discovery._lock_key("switch") == "discover:switch:lock"
    assert discovery._lock_key("iconbit") == "discover:iconbit:lock"
    assert scanner.SCAN_KEY_LOCK == "scan:lock"
