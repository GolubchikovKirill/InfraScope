from __future__ import annotations

from typing import cast

import pytest
from sqlmodel import Session

from app.domains.inventory import dhcp_clear
from app.domains.inventory.dhcp_clear import (
    get_eligible_switches_for_dhcp_clear,
    run_dhcp_clear_for_switch,
    switch_eligible_for_dhcp_clear,
)
from app.domains.inventory.models import NetworkSwitch
from app.services.cisco_dhcp import ROLE_EXTERNAL, ROLE_LOCAL_SERVER, DhcpClearPlan, DhcpClearResult


class _FakeExecResult:
    def __init__(self, rows) -> None:
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows=()) -> None:
        self._rows = list(rows)

    def exec(self, _stmt):
        return _FakeExecResult(self._rows)

    def add(self, _obj) -> None:
        pass

    def commit(self) -> None:
        pass


def _switch(name: str, *, vlan: int = 20, vendor: str = "cisco", mode: str = "live") -> NetworkSwitch:
    return NetworkSwitch(
        name=name,
        ip_address="172.19.17.9",
        ap_vlan=vlan,
        vendor=vendor,
        dhcp_clear_enabled=True,
        dhcp_clear_mode=mode,
    )


def test_eligibility_requires_cisco_vlan_20_and_allowlisted_store() -> None:
    allowed = {"A30"}
    assert switch_eligible_for_dhcp_clear(_switch("A30"), allowed) == (True, None)
    assert switch_eligible_for_dhcp_clear(_switch("A30", vendor="dlink"), allowed)[0] is False
    assert switch_eligible_for_dhcp_clear(_switch("A30", vlan=30), allowed)[0] is False
    ok, reason = switch_eligible_for_dhcp_clear(_switch("A31"), allowed)
    assert ok is False and "allowlist" in (reason or "")


def test_eligibility_matches_cyrillic_lookalike_store_names() -> None:
    assert switch_eligible_for_dhcp_clear(_switch("А30"), {"A30"})[0] is True  # Cyrillic А


def test_get_eligible_is_sorted_filtered_and_respects_the_global_switch(monkeypatch) -> None:
    monkeypatch.setattr(dhcp_clear.settings, "DHCP_CLEAR_ENABLED", True)
    monkeypatch.setattr(dhcp_clear.settings, "DHCP_CLEAR_ALLOWED_STORES", "A1,A2")
    session = _FakeSession([_switch("A2"), _switch("A1"), _switch("A3")])
    assert [s.name for s in get_eligible_switches_for_dhcp_clear(cast(Session, session))] == ["A1", "A2"]

    monkeypatch.setattr(dhcp_clear.settings, "DHCP_CLEAR_ENABLED", False)
    assert get_eligible_switches_for_dhcp_clear(cast(Session, session)) == []


def test_empty_allowlist_disables_everything(monkeypatch) -> None:
    monkeypatch.setattr(dhcp_clear.settings, "DHCP_CLEAR_ENABLED", True)
    monkeypatch.setattr(dhcp_clear.settings, "DHCP_CLEAR_ALLOWED_STORES", "")
    assert get_eligible_switches_for_dhcp_clear(cast(Session, _FakeSession([_switch("A1")]))) == []


def _patch_run(monkeypatch, result: DhcpClearResult | None, captured_kwargs: dict | None = None):
    def _fake(*_args, **kwargs):
        if captured_kwargs is not None:
            captured_kwargs.update(kwargs)
        return result

    monkeypatch.setattr(dhcp_clear, "run_dhcp_clear", _fake)
    events: list[dict] = []
    monkeypatch.setattr(dhcp_clear, "write_event_log", lambda _s, **kw: events.append(kw))
    return events


@pytest.mark.asyncio
async def test_unreachable_switch_is_logged_not_treated_as_clean(monkeypatch) -> None:
    events = _patch_run(monkeypatch, None)
    out = await run_dhcp_clear_for_switch(cast(Session, _FakeSession()), _switch("A30"))
    assert out["skipped"] == "switch_unreachable"
    assert [e["event_type"] for e in events] == ["dhcp_clear_skipped"]
    assert events[0]["severity"] == "warning"


@pytest.mark.asyncio
async def test_mode_decides_dry_run_and_actions_come_from_settings(monkeypatch) -> None:
    monkeypatch.setattr(dhcp_clear.settings, "DHCP_CLEAR_ACTIONS", "conflict, reload ,BINDING")
    plan = DhcpClearPlan(commands=["clear ip dhcp conflict *"], conflicts_to_clear=2)
    result = DhcpClearResult(dry_run=True, role=ROLE_LOCAL_SERVER, plan=plan, conflicts_before=2)
    kwargs: dict = {}
    events = _patch_run(monkeypatch, result, kwargs)

    out = await run_dhcp_clear_for_switch(cast(Session, _FakeSession()), _switch("A30", mode="dry_run"))

    assert kwargs["dry_run"] is True
    assert kwargs["actions"] == {"conflict", "binding"}  # junk dropped, case-folded
    assert events[0]["event_type"] == "dhcp_clear_dry_run"
    assert "[DRY RUN]" in events[0]["message"]
    assert out["commands_planned"] == 1


@pytest.mark.asyncio
async def test_live_success_logs_before_and_after(monkeypatch) -> None:
    plan = DhcpClearPlan(commands=["clear ip dhcp binding 10.20.0.4"], bindings_to_clear=1)
    result = DhcpClearResult(
        dry_run=False,
        role=ROLE_LOCAL_SERVER,
        plan=plan,
        bindings_cleared=1,
        bindings_before=1,
        bindings_after=0,
        conflicts_after=0,
    )
    kwargs: dict = {}
    events = _patch_run(monkeypatch, result, kwargs)

    out = await run_dhcp_clear_for_switch(cast(Session, _FakeSession()), _switch("A30", mode="live"))

    assert kwargs["dry_run"] is False
    assert events[0]["event_type"] == "dhcp_clear"
    assert "1 -> 0" in events[0]["message"]
    assert out["bindings_cleared"] == 1


@pytest.mark.asyncio
async def test_live_partial_failure_is_an_error_event(monkeypatch) -> None:
    plan = DhcpClearPlan(commands=["a", "b"], bindings_to_clear=2)
    result = DhcpClearResult(
        dry_run=False, role=ROLE_LOCAL_SERVER, plan=plan, bindings_cleared=1, errors=["b: % Invalid input"]
    )
    events = _patch_run(monkeypatch, result)
    out = await run_dhcp_clear_for_switch(cast(Session, _FakeSession()), _switch("A30"))
    assert events[0]["event_type"] == "dhcp_clear_failed"
    assert events[0]["severity"] == "error"
    assert out["errors"] == ["b: % Invalid input"]


@pytest.mark.asyncio
async def test_nothing_to_do_explains_why(monkeypatch) -> None:
    plan = DhcpClearPlan(skipped=["switch is not the DHCP server for VLAN 20 (role=external); ..."])
    result = DhcpClearResult(dry_run=False, role=ROLE_EXTERNAL, plan=plan)
    events = _patch_run(monkeypatch, result)
    await run_dhcp_clear_for_switch(cast(Session, _FakeSession()), _switch("A30"))
    assert events[0]["event_type"] == "dhcp_clear_skipped"
    assert "not the DHCP server" in events[0]["message"]
