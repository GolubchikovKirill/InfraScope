from __future__ import annotations

import pytest

from app.domains.inventory.models import NetworkSwitch
from app.domains.inventory.switch_polling import apply_switch_poll_info, poll_one_switch
from app.services.switches.base import SwitchPollInfo


def test_apply_switch_poll_info_updates_online_metadata() -> None:
    switch = NetworkSwitch(
        name="Core Switch",
        ip_address="10.10.10.30",
    )
    info = SwitchPollInfo(
        is_online=True,
        hostname="SW-CORE-01",
        model_info="WS-C2960X",
        ios_version="15.2(7)E",
        uptime="2d 5h",
    )

    apply_switch_poll_info(switch, info)

    assert switch.is_online is True
    assert switch.hostname == "SW-CORE-01"
    assert switch.model_info == "WS-C2960X"
    assert switch.ios_version == "15.2(7)E"
    assert switch.uptime == "2d 5h"
    assert switch.last_polled_at is not None


def test_apply_switch_poll_info_preserves_existing_metadata_when_poll_is_sparse() -> None:
    switch = NetworkSwitch(
        name="Core Switch",
        ip_address="10.10.10.30",
        hostname="SW-CORE-01",
        model_info="WS-C2960X",
        ios_version="15.2(7)E",
        uptime="2d 5h",
    )

    apply_switch_poll_info(switch, SwitchPollInfo(is_online=False))

    assert switch.is_online is False
    assert switch.hostname == "SW-CORE-01"
    assert switch.model_info == "WS-C2960X"
    assert switch.ios_version == "15.2(7)E"
    assert switch.uptime == "2d 5h"


def test_apply_switch_poll_info_can_use_resilience_effective_status() -> None:
    switch = NetworkSwitch(name="Core Switch", ip_address="10.10.10.30")

    apply_switch_poll_info(switch, SwitchPollInfo(is_online=False), effective_online=True)

    assert switch.is_online is True


@pytest.mark.asyncio
async def test_poll_one_switch_returns_provider_info(monkeypatch) -> None:
    switch = NetworkSwitch(name="Core Switch", ip_address="10.10.10.30")

    class _Provider:
        def poll_switch(self, _switch: NetworkSwitch) -> SwitchPollInfo:
            return SwitchPollInfo(is_online=True, hostname="SW-CORE-01")

    async def no_jitter() -> None:
        return None

    monkeypatch.setattr("app.domains.inventory.switch_polling.poll_jitter_async", no_jitter)
    monkeypatch.setattr("app.domains.inventory.switch_polling.resolve_switch_provider", lambda _switch: _Provider())

    polled_switch, info, exc = await poll_one_switch(switch)

    assert polled_switch is switch
    assert exc is None
    assert info == SwitchPollInfo(is_online=True, hostname="SW-CORE-01")
