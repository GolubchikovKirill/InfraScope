"""The polling and discovery work used to be reached over HTTP in production
(polling-service / discovery-service) while the code these tests exercise - the
worker's own "local" branch - never ran there. These pin what the worker does
now that it is the only path."""

from __future__ import annotations

import httpx
import pytest

from app.domains.inventory.models import NetworkSwitch
from app.worker import tasks


@pytest.fixture
def no_http(monkeypatch: pytest.MonkeyPatch):
    """Any HTTP call from a task is a regression: nothing to call any more."""

    def _forbidden(*_a, **_kw):
        raise AssertionError("worker task must not call an internal service over HTTP")

    monkeypatch.setattr(httpx, "Client", _forbidden)
    monkeypatch.setattr(httpx, "AsyncClient", _forbidden)


def test_poll_all_switches_uses_the_bulk_poll_not_a_one_by_one_loop(monkeypatch, no_http, db_session):
    """Regression guard for a parity gap found while removing polling-service:
    the worker's fallback polled switches one at a time via poll_switch_local,
    while the service ran the bulk poll_all_switches_local (concurrent, and it
    detects a whole subnet going dark as a path failure)."""
    db_session.add(NetworkSwitch(name="sw1", ip_address="10.0.0.1", is_online=True))
    db_session.add(NetworkSwitch(name="sw2", ip_address="10.0.0.2", is_online=False))
    db_session.commit()

    calls: list[str] = []

    async def _bulk(*, session):
        calls.append("bulk")

    async def _single(*, session, switch_id):
        calls.append("single")

    monkeypatch.setattr(tasks, "poll_all_switches_local", _bulk)
    monkeypatch.setattr(tasks, "poll_switch_local", _single)
    monkeypatch.setattr(tasks, "engine", db_session.get_bind())

    result = tasks.poll_all_switches_task.run()

    assert calls == ["bulk"]
    assert result["total"] == 2
    assert result["online"] == 1
    assert {s["name"] for s in result["switches"]} == {"sw1", "sw2"}


@pytest.mark.parametrize(
    ("task", "attr", "kwargs"),
    [
        (tasks.poll_all_printers_task, "poll_all_printers_local", {"printer_type": "laser"}),
        (tasks.poll_all_media_players_task, "poll_all_media_players_local", {"device_type": None}),
        (tasks.poll_all_cash_registers_task, "poll_all_cash_registers_local", {}),
    ],
)
def test_bulk_poll_tasks_run_in_process(monkeypatch, no_http, db_session, task, attr, kwargs):
    ran: list[bool] = []

    async def _fake(**_kw):
        ran.append(True)

    monkeypatch.setattr(tasks, attr, _fake)
    monkeypatch.setattr(tasks, "engine", db_session.get_bind())

    result = task.run(**kwargs)

    assert ran == [True]
    assert result["total"] == 0


def test_discovery_scan_dispatches_printer_scans_to_scan_subnet(monkeypatch, no_http):
    seen: dict = {}

    async def _scan_subnet(subnet, ports, known):
        seen["args"] = (subnet, ports, known)
        return [{"ip": "10.0.0.5"}]

    async def _never(*_a, **_kw):
        raise AssertionError("printer scans go through scan_subnet")

    monkeypatch.setattr(tasks, "scan_subnet", _scan_subnet)
    monkeypatch.setattr(tasks, "run_discovery_scan", _never)

    result = tasks.discovery_scan_task.run("printers", "10.0.0.0/30", "9100", [{"id": "1"}])

    assert seen["args"] == ("10.0.0.0/30", "9100", [{"id": "1"}])
    assert result["kind"] == "printers"
    assert result["found_devices"] == 1


@pytest.mark.parametrize("kind", ["iconbit", "switch"])
def test_discovery_scan_dispatches_other_kinds_to_run_discovery_scan(monkeypatch, no_http, kind):
    seen: dict = {}

    async def _run(k, subnet, ports, known):
        seen["args"] = (k, subnet, ports, known)
        return []

    async def _never(*_a, **_kw):
        raise AssertionError("only printer scans use scan_subnet")

    monkeypatch.setattr(tasks, "run_discovery_scan", _run)
    monkeypatch.setattr(tasks, "scan_subnet", _never)

    result = tasks.discovery_scan_task.run(kind, "10.0.0.0/30", "22", [])

    assert seen["args"] == (kind, "10.0.0.0/30", "22", [])
    assert result["found_devices"] == 0


def test_discovery_scan_errors_propagate_without_retrying(monkeypatch, no_http):
    async def _boom(*_a, **_kw):
        raise RuntimeError("Scan already in progress")

    monkeypatch.setattr(tasks, "scan_subnet", _boom)

    with pytest.raises(RuntimeError, match="already in progress"):
        tasks.discovery_scan_task.run("printers", "10.0.0.0/30", "9100", [])

    # a person starts a scan and the error is already published through the
    # progress key - retrying would just re-run a scan nobody asked for twice
    assert not getattr(tasks.discovery_scan_task, "autoretry_for", ())
