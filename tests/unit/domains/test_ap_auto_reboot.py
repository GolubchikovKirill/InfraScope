from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.domains.inventory.ap_auto_reboot import run_ap_reboot_for_switch
from app.domains.inventory.ap_registry import MergedAccessPoint, set_ap_excluded
from app.domains.inventory.models import NetworkSwitch, SwitchAccessPoint


class _FakeSession:
    def add(self, _obj) -> None:
        pass

    def commit(self) -> None:
        pass


@pytest.mark.asyncio
async def test_run_ap_reboot_for_switch_skips_without_touching_registry_when_switch_unreachable(
    monkeypatch,
) -> None:
    """A failed SSH scan must never be treated as 'every known AP is hung'."""
    switch = NetworkSwitch(name="A11", ip_address="172.19.17.111", ap_vlan=20, auto_reboot_mode="live")

    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.get_access_points", lambda *a, **kw: None)

    def _must_not_be_called(*_a, **_kw):
        raise AssertionError("registry must not be touched when the switch could not be scanned")

    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.record_seen_aps", _must_not_be_called)
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.merge_live_and_known", _must_not_be_called)
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.poe_cycle_ap", _must_not_be_called)

    captured: dict = {}

    def _fake_write_event_log(_session, **kwargs) -> None:
        captured.update(kwargs)

    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.write_event_log", _fake_write_event_log)

    result = await run_ap_reboot_for_switch(_FakeSession(), switch)

    assert result["skipped"] == "switch_unreachable"
    assert result["results"] == []
    assert captured["event_type"] == "ap_auto_reboot_skipped"
    assert captured["severity"] == "warning"


@pytest.mark.asyncio
async def test_run_ap_reboot_logs_failure_when_ap_does_not_come_back_online(monkeypatch) -> None:
    """Regression test: a real production cycle hit an AttributeError here
    (switch.vlan instead of switch.ap_vlan) exactly on this path - a
    successfully-sent reboot whose AP then fails to reappear - which crashed
    the task before the failure could even be logged."""
    switch = NetworkSwitch(name="VN3", ip_address="172.19.17.133", ap_vlan=20, auto_reboot_mode="live")
    ap = MergedAccessPoint(
        mac_address="88:5a:92:17:03:fb",
        port="Gi1/0/40",
        vlan=20,
        cdp_name=None,
        ip_address=None,
        cdp_platform=None,
        poe_power="15.4W",
        poe_status="on",
        is_responding=True,
        last_seen_at=None,
        exclude_from_auto_reboot=False,
    )

    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.get_access_points", lambda *a, **kw: [])
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.record_seen_aps", lambda *a, **kw: None)
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.get_known_aps", lambda *a, **kw: [])
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.merge_live_and_known", lambda *a, **kw: [ap])
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.poe_cycle_ap", lambda *a, **kw: True)
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot._verify_ap_back_online", lambda *a, **kw: _false())
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.register_reboot_outcome", lambda *a, **kw: (None, False))

    captured: list[dict] = []
    monkeypatch.setattr(
        "app.domains.inventory.ap_auto_reboot.write_event_log",
        lambda _session, **kwargs: captured.append(kwargs),
    )

    result = await run_ap_reboot_for_switch(_FakeSession(), switch)

    failure_events = [c for c in captured if c["event_type"] == "ap_auto_reboot_failed"]
    assert len(failure_events) == 1
    assert "VLAN 20" in failure_events[0]["message"]
    assert result["results"][0]["ok"] is True
    assert result["results"][0]["back_online"] is False


async def _false() -> bool:
    return False


async def _true() -> bool:
    return True


def _make_switch_and_hung_ap(db_session, *, name: str = "TestSW") -> tuple[NetworkSwitch, SwitchAccessPoint]:
    switch = NetworkSwitch(name=name, ip_address="10.0.0.1", ap_vlan=20, auto_reboot_mode="live")
    db_session.add(switch)
    db_session.commit()
    db_session.refresh(switch)

    ap_row = SwitchAccessPoint(switch_id=switch.id, mac_address="aa:bb:cc:dd:ee:01", port="Gi1/0/1")
    db_session.add(ap_row)
    db_session.commit()
    db_session.refresh(ap_row)
    return switch, ap_row


@pytest.mark.asyncio
async def test_ap_escalates_after_consecutive_reboot_failures(db_session, monkeypatch) -> None:
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.settings.AUTO_REBOOT_AP_ESCALATE_AFTER_CYCLES", 2)
    switch, ap_row = _make_switch_and_hung_ap(db_session)

    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.get_access_points", lambda *a, **kw: [])
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.get_port_poe_power", lambda *a, **kw: "15.4W")
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.poe_cycle_ap", lambda *a, **kw: True)
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot._verify_ap_back_online", lambda *a, **kw: _false())

    captured: list[dict] = []
    monkeypatch.setattr(
        "app.domains.inventory.ap_auto_reboot.write_event_log",
        lambda _session, **kwargs: captured.append(kwargs),
    )

    await run_ap_reboot_for_switch(db_session, switch)
    db_session.refresh(ap_row)
    assert ap_row.consecutive_reboot_failures == 1
    assert ap_row.needs_attention_since is None
    assert not any(c["event_type"] == "ap_auto_reboot_needs_attention" for c in captured)

    await run_ap_reboot_for_switch(db_session, switch)
    db_session.refresh(ap_row)
    assert ap_row.consecutive_reboot_failures == 2
    assert ap_row.needs_attention_since is not None
    assert ap_row.exclude_from_auto_reboot is True

    escalation_events = [c for c in captured if c["event_type"] == "ap_auto_reboot_needs_attention"]
    assert len(escalation_events) == 1
    assert escalation_events[0]["severity"] == "critical"


@pytest.mark.asyncio
async def test_ap_escalates_after_consecutive_no_power_skips(db_session, monkeypatch) -> None:
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.settings.AUTO_REBOOT_AP_ESCALATE_AFTER_CYCLES", 2)
    switch, ap_row = _make_switch_and_hung_ap(db_session)

    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.get_access_points", lambda *a, **kw: [])
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.get_port_poe_power", lambda *a, **kw: None)

    def _must_not_be_called(*_a, **_kw):
        raise AssertionError("a port with no PoE draw must never be power-cycled")

    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.poe_cycle_ap", _must_not_be_called)

    captured: list[dict] = []
    monkeypatch.setattr(
        "app.domains.inventory.ap_auto_reboot.write_event_log",
        lambda _session, **kwargs: captured.append(kwargs),
    )

    await run_ap_reboot_for_switch(db_session, switch)
    await run_ap_reboot_for_switch(db_session, switch)
    db_session.refresh(ap_row)

    assert ap_row.consecutive_no_power_skips == 2
    assert ap_row.needs_attention_since is not None
    assert ap_row.exclude_from_auto_reboot is True
    assert any(c["event_type"] == "ap_auto_reboot_needs_attention" for c in captured)


@pytest.mark.asyncio
async def test_verified_recovery_resets_failure_streak(db_session, monkeypatch) -> None:
    switch, ap_row = _make_switch_and_hung_ap(db_session)
    ap_row.consecutive_reboot_failures = 1
    db_session.add(ap_row)
    db_session.commit()

    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.get_access_points", lambda *a, **kw: [])
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.get_port_poe_power", lambda *a, **kw: "15.4W")
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.poe_cycle_ap", lambda *a, **kw: True)
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot._verify_ap_back_online", lambda *a, **kw: _true())
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.write_event_log", lambda _session, **kwargs: None)

    await run_ap_reboot_for_switch(db_session, switch)
    db_session.refresh(ap_row)

    assert ap_row.consecutive_reboot_failures == 0
    assert ap_row.needs_attention_since is None


def test_set_ap_excluded_false_resets_escalation_state(db_session) -> None:
    switch, ap_row = _make_switch_and_hung_ap(db_session)
    ap_row.exclude_from_auto_reboot = True
    ap_row.consecutive_reboot_failures = 2
    from datetime import UTC, datetime

    ap_row.needs_attention_since = datetime.now(UTC)
    db_session.add(ap_row)
    db_session.commit()

    ok = set_ap_excluded(db_session, switch_id=switch.id, mac_address=ap_row.mac_address, excluded=False)

    assert ok is True
    db_session.refresh(ap_row)
    assert ap_row.exclude_from_auto_reboot is False
    assert ap_row.consecutive_reboot_failures == 0
    assert ap_row.needs_attention_since is None


@pytest.mark.asyncio
async def test_switch_escalates_after_consecutive_unreachable_cycles(db_session, monkeypatch) -> None:
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.settings.AUTO_REBOOT_AP_ESCALATE_AFTER_CYCLES", 2)
    switch = NetworkSwitch(name="TestUnreachable", ip_address="10.0.0.2", ap_vlan=20, auto_reboot_mode="live")
    db_session.add(switch)
    db_session.commit()
    db_session.refresh(switch)

    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.get_access_points", lambda *a, **kw: None)

    captured: list[dict] = []
    monkeypatch.setattr(
        "app.domains.inventory.ap_auto_reboot.write_event_log",
        lambda _session, **kwargs: captured.append(kwargs),
    )

    await run_ap_reboot_for_switch(db_session, switch)
    db_session.refresh(switch)
    assert switch.consecutive_unreachable_cycles == 1
    assert switch.switch_needs_attention_since is None

    await run_ap_reboot_for_switch(db_session, switch)
    db_session.refresh(switch)
    assert switch.consecutive_unreachable_cycles == 2
    assert switch.switch_needs_attention_since is not None

    escalations = [c for c in captured if c["event_type"] == "ap_auto_reboot_switch_needs_attention"]
    assert len(escalations) == 1
    assert escalations[0]["severity"] == "critical"
    assert "SSH" in escalations[0]["message"]


@pytest.mark.asyncio
async def test_switch_escalates_after_consecutive_no_aps_found_cycles(db_session, monkeypatch) -> None:
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.settings.AUTO_REBOOT_AP_ESCALATE_AFTER_CYCLES", 2)
    switch = NetworkSwitch(name="TestNoAps", ip_address="10.0.0.3", ap_vlan=20, auto_reboot_mode="live")
    db_session.add(switch)
    db_session.commit()
    db_session.refresh(switch)

    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.get_access_points", lambda *a, **kw: [])

    captured: list[dict] = []
    monkeypatch.setattr(
        "app.domains.inventory.ap_auto_reboot.write_event_log",
        lambda _session, **kwargs: captured.append(kwargs),
    )

    await run_ap_reboot_for_switch(db_session, switch)
    await run_ap_reboot_for_switch(db_session, switch)
    db_session.refresh(switch)

    assert switch.consecutive_no_aps_found_cycles == 2
    assert switch.switch_needs_attention_since is not None
    escalations = [c for c in captured if c["event_type"] == "ap_auto_reboot_switch_needs_attention"]
    assert len(escalations) == 1
    assert "VLAN" in escalations[0]["message"]


@pytest.mark.asyncio
async def test_switch_needs_attention_clears_on_healthy_cycle(db_session, monkeypatch) -> None:
    switch = NetworkSwitch(name="TestRecovers", ip_address="10.0.0.4", ap_vlan=20, auto_reboot_mode="live")
    switch.switch_needs_attention_since = datetime.now(UTC)
    switch.consecutive_no_aps_found_cycles = 3
    db_session.add(switch)
    db_session.commit()
    db_session.refresh(switch)

    ap = MergedAccessPoint(
        mac_address="aa:bb:cc:dd:ee:02",
        port="Gi1/0/2",
        vlan=20,
        cdp_name=None,
        ip_address=None,
        cdp_platform=None,
        poe_power="15.4W",
        poe_status="on",
        is_responding=True,
        last_seen_at=None,
        exclude_from_auto_reboot=False,
    )
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.get_access_points", lambda *a, **kw: [])
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.record_seen_aps", lambda *a, **kw: None)
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.get_known_aps", lambda *a, **kw: [])
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.merge_live_and_known", lambda *a, **kw: [ap])
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.poe_cycle_ap", lambda *a, **kw: True)
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot._verify_ap_back_online", lambda *a, **kw: _true())
    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.write_event_log", lambda _session, **kwargs: None)

    await run_ap_reboot_for_switch(db_session, switch)
    db_session.refresh(switch)

    assert switch.consecutive_no_aps_found_cycles == 0
    assert switch.switch_needs_attention_since is None


@pytest.mark.asyncio
async def test_all_excluded_does_not_count_toward_no_aps_found_streak(db_session, monkeypatch) -> None:
    """A switch whose only known AP was deliberately excluded shouldn't be
    confused with one that genuinely has none on its VLAN - and shouldn't
    count toward the no-APs-found escalation streak either."""
    switch = NetworkSwitch(name="TestAllExcluded", ip_address="10.0.0.5", ap_vlan=20, auto_reboot_mode="live")
    db_session.add(switch)
    db_session.commit()
    db_session.refresh(switch)

    ap_row = SwitchAccessPoint(
        switch_id=switch.id,
        mac_address="aa:bb:cc:dd:ee:03",
        port="Gi1/0/3",
        exclude_from_auto_reboot=True,
    )
    db_session.add(ap_row)
    db_session.commit()

    monkeypatch.setattr("app.domains.inventory.ap_auto_reboot.get_access_points", lambda *a, **kw: [])

    captured: list[dict] = []
    monkeypatch.setattr(
        "app.domains.inventory.ap_auto_reboot.write_event_log",
        lambda _session, **kwargs: captured.append(kwargs),
    )

    result = await run_ap_reboot_for_switch(db_session, switch)
    db_session.refresh(switch)

    assert switch.consecutive_no_aps_found_cycles == 0
    assert result["aps_found"] == 0
    skip_events = [c for c in captured if c["event_type"] == "ap_auto_reboot_skipped"]
    assert len(skip_events) == 1
    assert "all excluded" in skip_events[0]["message"]
