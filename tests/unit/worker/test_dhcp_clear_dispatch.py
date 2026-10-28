from __future__ import annotations

import pytest

from app.domains.inventory.models import NetworkSwitch
from app.worker.celery_app import celery_app
from app.worker.tasks import dhcp_clear_cycle_task, dhcp_clear_switch_task


class _FakeSession:
    def __init__(self, by_id=None) -> None:
        self._by_id = by_id or {}

    def get(self, _model, obj_id):
        return self._by_id.get(obj_id)

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        return None


class _FakeLease:
    def mark_attempted(self) -> None:
        pass

    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _allow_lease(monkeypatch):
    monkeypatch.setattr("app.worker.tasks._acquire_dhcp_clear_lease", lambda **_kw: (_FakeLease(), None))


def _switch(name: str, *, enabled: bool = True) -> NetworkSwitch:
    return NetworkSwitch(name=name, ip_address="172.19.17.9", ap_vlan=20, dhcp_clear_enabled=enabled)


def test_cycle_dispatches_one_staggered_task_per_switch(monkeypatch) -> None:
    switches = [_switch("A1"), _switch("A2")]
    monkeypatch.setattr("app.worker.tasks.get_eligible_switches_for_dhcp_clear", lambda _s: switches)
    monkeypatch.setattr("app.worker.tasks.settings.DHCP_CLEAR_STAGGER_SECONDS", 30)
    monkeypatch.setattr("app.worker.tasks.Session", lambda _engine: _FakeSession())
    captured: list[dict] = []
    monkeypatch.setattr(
        dhcp_clear_switch_task, "apply_async", lambda args, countdown: captured.append({"a": args, "c": countdown})
    )

    result = dhcp_clear_cycle_task.apply().get()

    assert result["switches_scheduled"] == 2
    assert [c["c"] for c in captured] == [0, 30]
    assert len({c["a"][1] for c in captured}) == 1


def test_switch_task_skips_when_disabled_since_dispatch(monkeypatch) -> None:
    switch = _switch("A1", enabled=False)
    monkeypatch.setattr("app.worker.tasks.Session", lambda _e: _FakeSession({switch.id: switch}))

    def _must_not_run(*_a, **_kw):
        raise AssertionError("a disabled switch must not be touched")

    monkeypatch.setattr("app.worker.tasks.run_dhcp_clear_for_switch", _must_not_run)
    assert dhcp_clear_switch_task.apply(args=[str(switch.id)]).get()["status"] == "disabled_since_dispatch"


def test_switch_task_skips_when_no_longer_allowlisted(monkeypatch) -> None:
    switch = _switch("A9")
    monkeypatch.setattr("app.worker.tasks.Session", lambda _e: _FakeSession({switch.id: switch}))
    monkeypatch.setattr("app.worker.tasks.settings.DHCP_CLEAR_ALLOWED_STORES", "A1")

    def _must_not_run(*_a, **_kw):
        raise AssertionError("an unallowlisted switch must not be touched")

    monkeypatch.setattr("app.worker.tasks.run_dhcp_clear_for_switch", _must_not_run)
    assert dhcp_clear_switch_task.apply(args=[str(switch.id)]).get()["status"] == "no_longer_eligible"


def test_switch_task_skips_duplicate_delivery_before_touching_the_switch(monkeypatch) -> None:
    switch = _switch("A1")
    monkeypatch.setattr("app.worker.tasks.Session", lambda _e: _FakeSession({switch.id: switch}))
    monkeypatch.setattr("app.worker.tasks._acquire_dhcp_clear_lease", lambda **_kw: (None, "already_running"))

    def _must_not_run(*_a, **_kw):
        raise AssertionError("duplicate delivery must not reach the switch")

    monkeypatch.setattr("app.worker.tasks.run_dhcp_clear_for_switch", _must_not_run)
    result = dhcp_clear_switch_task.apply(args=[str(switch.id), "cycle-1"]).get()
    assert result["status"] == "already_running" and result["cycle_id"] == "cycle-1"


def test_dhcp_clear_runs_before_the_ap_reboot_cycle() -> None:
    schedule = celery_app.conf.beat_schedule
    clears = {k: v for k, v in schedule.items() if v["task"] == "tasks.dhcp_clear_cycle"}
    assert len(clears) == 2
    for entry in clears.values():
        assert entry["schedule"]._orig_minute == 10  # 20 min ahead of the :30 reboot
