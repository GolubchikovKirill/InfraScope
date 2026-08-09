from __future__ import annotations

import pytest

from app.domains.inventory.ap_auto_reboot import get_eligible_switches_for_auto_reboot
from app.domains.inventory.models import NetworkSwitch
from app.worker.tasks import ap_auto_reboot_cycle_task, ap_auto_reboot_switch_task


class _FakeExecResult:
    def __init__(self, rows) -> None:
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows=(), by_id=None) -> None:
        self._rows = list(rows)
        self._by_id = by_id or {}

    def exec(self, _stmt):
        return _FakeExecResult(self._rows)

    def get(self, _model, obj_id):
        return self._by_id.get(obj_id)

    def commit(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        return None


class _FakeLease:
    def __init__(self) -> None:
        self.attempted = False
        self.closed = False

    def mark_attempted(self) -> None:
        self.attempted = True

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _allow_auto_reboot_lease(monkeypatch):
    """Unit tests do not depend on a running Redis instance."""
    monkeypatch.setattr(
        "app.worker.tasks._acquire_auto_reboot_lease",
        lambda **_kwargs: (_FakeLease(), None),
    )


def _switch(name: str, *, enabled: bool = True, vlan: int = 20, mode: str = "live") -> NetworkSwitch:
    return NetworkSwitch(
        name=name,
        ip_address=f"172.19.17.{abs(hash(name)) % 250 + 1}",
        auto_reboot_aps_enabled=enabled,
        auto_reboot_mode=mode,
        ap_vlan=vlan,
    )


def test_get_eligible_switches_sorted_and_filtered_by_allowlist(monkeypatch) -> None:
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.settings.AUTO_REBOOT_AP_ENABLED", True)
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.settings.AUTO_REBOOT_AP_ALLOWED_STORES", "A1,A2")

    rows = [_switch("A2"), _switch("A1"), _switch("A3")]  # A3 not in allowlist
    session = _FakeSession(rows=rows)

    result = get_eligible_switches_for_auto_reboot(session)

    assert [sw.name for sw in result] == ["A1", "A2"]


def test_get_eligible_switches_empty_when_globally_disabled(monkeypatch) -> None:
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.settings.AUTO_REBOOT_AP_ENABLED", False)
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.settings.AUTO_REBOOT_AP_ALLOWED_STORES", "A1")

    session = _FakeSession(rows=[_switch("A1")])

    assert get_eligible_switches_for_auto_reboot(session) == []


def test_cycle_task_dispatches_one_subtask_per_switch_with_stagger(monkeypatch) -> None:
    switches = [_switch("A1"), _switch("A2"), _switch("A3")]
    monkeypatch.setattr(
        "app.worker.tasks.get_eligible_switches_for_auto_reboot",
        lambda _session: switches,
    )
    monkeypatch.setattr("app.worker.tasks.settings.AUTO_REBOOT_AP_STAGGER_SECONDS", 90)
    monkeypatch.setattr("app.worker.tasks.Session", lambda _engine: _FakeSession())

    captured: list[dict] = []

    def _fake_apply_async(args, countdown):
        captured.append({"args": args, "countdown": countdown})

    monkeypatch.setattr(ap_auto_reboot_switch_task, "apply_async", _fake_apply_async)

    result = ap_auto_reboot_cycle_task.apply().get()

    assert result["switches_scheduled"] == 3
    assert [c["countdown"] for c in captured] == [0, 90, 180]
    assert [c["args"][0] for c in captured] == [str(sw.id) for sw in switches]
    assert len({c["args"][1] for c in captured}) == 1


def test_switch_task_skips_when_disabled_since_dispatch(monkeypatch) -> None:
    switch = _switch("A1", enabled=False)
    monkeypatch.setattr("app.worker.tasks.Session", lambda _engine: _FakeSession(by_id={switch.id: switch}))

    def _must_not_run(*_a, **_kw):
        raise AssertionError("a disabled switch must not be rebooted")

    monkeypatch.setattr("app.worker.tasks.run_ap_reboot_for_switch", _must_not_run)

    result = ap_auto_reboot_switch_task.apply(args=[str(switch.id)]).get()

    assert result["status"] == "disabled_since_dispatch"


def test_switch_task_skips_when_no_longer_eligible(monkeypatch) -> None:
    switch = _switch("A9")  # enabled, but not in the allowlist below
    monkeypatch.setattr("app.worker.tasks.Session", lambda _engine: _FakeSession(by_id={switch.id: switch}))
    monkeypatch.setattr("app.worker.tasks.settings.AUTO_REBOOT_AP_ALLOWED_STORES", "A1")

    def _must_not_run(*_a, **_kw):
        raise AssertionError("an unallowlisted switch must not be rebooted")

    monkeypatch.setattr("app.worker.tasks.run_ap_reboot_for_switch", _must_not_run)

    result = ap_auto_reboot_switch_task.apply(args=[str(switch.id)]).get()

    assert result["status"] == "no_longer_eligible"


def test_switch_task_skips_duplicate_delivery_before_hardware_call(monkeypatch) -> None:
    switch = _switch("A1")
    monkeypatch.setattr("app.worker.tasks.Session", lambda _engine: _FakeSession(by_id={switch.id: switch}))
    monkeypatch.setattr(
        "app.worker.tasks._acquire_auto_reboot_lease",
        lambda **_kwargs: (None, "already_running"),
    )

    def _must_not_run(*_args, **_kwargs):
        raise AssertionError("duplicate delivery must not reach live hardware code")

    monkeypatch.setattr("app.worker.tasks.run_ap_reboot_for_switch", _must_not_run)

    result = ap_auto_reboot_switch_task.apply(args=[str(switch.id), "scheduled-cycle-1"]).get()

    assert result["status"] == "already_running"
    assert result["cycle_id"] == "scheduled-cycle-1"
