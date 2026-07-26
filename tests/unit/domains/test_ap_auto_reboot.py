from __future__ import annotations

import pytest

from app.domains.inventory.ap_auto_reboot import run_ap_reboot_for_switch
from app.domains.inventory.ap_registry import MergedAccessPoint
from app.domains.inventory.models import NetworkSwitch


class _FakeSession:
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
