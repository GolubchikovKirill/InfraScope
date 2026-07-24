from __future__ import annotations

import pytest

from app.domains.inventory.ap_auto_reboot import run_ap_reboot_for_switch
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
