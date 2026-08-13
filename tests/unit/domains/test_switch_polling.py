from __future__ import annotations

import pytest

from app.domains.inventory.models import NetworkSwitch
from app.domains.inventory.switch_polling import (
    _subnets_with_total_failure,
    apply_switch_poll_info,
    poll_one_switch,
    record_switch_status_change,
)
from app.services.switches.base import SwitchPollInfo


def _sw(ip: str) -> NetworkSwitch:
    return NetworkSwitch(name=ip, ip_address=ip)


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


def test_apply_switch_poll_info_records_offline_reason() -> None:
    """A network-path failure and a rejected password must not look the
    same on the switch row - that ambiguity is what turned a 3-day Docker
    network misconfiguration into "the passwords must be wrong"."""
    switch = NetworkSwitch(name="Core Switch", ip_address="10.10.10.30")

    apply_switch_poll_info(switch, SwitchPollInfo(is_online=False, offline_reason="network_unreachable"))

    assert switch.is_online is False
    assert switch.reachability_reason == "network_unreachable"


def test_apply_switch_poll_info_clears_reason_when_back_online() -> None:
    switch = NetworkSwitch(name="Core Switch", ip_address="10.10.10.30", reachability_reason="auth_rejected")

    apply_switch_poll_info(switch, SwitchPollInfo(is_online=True, hostname="SW-CORE-01"))

    assert switch.is_online is True
    assert switch.reachability_reason is None


def test_record_switch_status_change_includes_offline_reason_in_message(monkeypatch) -> None:
    switch = NetworkSwitch(name="Core Switch", ip_address="10.10.10.30")
    switch.is_online = False
    switch.reachability_reason = "network_unreachable"

    events: list[dict] = []
    monkeypatch.setattr(
        "app.domains.inventory.switch_polling.write_event_log",
        lambda _session, **kwargs: events.append(kwargs),
    )

    record_switch_status_change(session=None, switch=switch, was_online=True)

    assert len(events) == 1
    assert events[0]["event_type"] == "device_offline"
    assert "путь до устройства недоступен" in events[0]["message"]


def test_record_switch_status_change_omits_reason_suffix_when_none(monkeypatch) -> None:
    switch = NetworkSwitch(name="Core Switch", ip_address="10.10.10.30")
    switch.is_online = True

    events: list[dict] = []
    monkeypatch.setattr(
        "app.domains.inventory.switch_polling.write_event_log",
        lambda _session, **kwargs: events.append(kwargs),
    )

    record_switch_status_change(session=None, switch=switch, was_online=False)

    assert events[0]["message"] == "Network device 'Core Switch' is now online"


def test_whole_switch_subnet_failing_at_once_is_flagged_as_a_path_problem(monkeypatch) -> None:
    """Switches don't all fail inside one poll cycle - the path does. Same
    heuristic, same rationale as printer_polling's, and the exact blind spot
    that turned a Docker network misconfiguration into 32 separate "device
    offline" records instead of one path warning."""
    monkeypatch.setattr("app.domains.inventory.switch_polling.settings.POLL_PATH_FAILURE_MIN_DEVICES", 3)
    monkeypatch.setattr("app.domains.inventory.switch_polling.settings.POLL_PATH_FAILURE_RATIO", 0.8)

    results = [
        (_sw("172.19.17.10"), None, None, RuntimeError("unreachable")),
        (_sw("172.19.17.11"), None, None, RuntimeError("unreachable")),
        (_sw("172.19.17.12"), None, None, RuntimeError("unreachable")),
        (_sw("172.19.17.13"), None, None, RuntimeError("unreachable")),
    ]

    assert _subnets_with_total_failure(results) == {"172.19.17"}


def test_one_switch_down_among_healthy_neighbours_is_not_a_path_problem(monkeypatch) -> None:
    monkeypatch.setattr("app.domains.inventory.switch_polling.settings.POLL_PATH_FAILURE_MIN_DEVICES", 3)
    monkeypatch.setattr("app.domains.inventory.switch_polling.settings.POLL_PATH_FAILURE_RATIO", 0.8)

    results = [
        (_sw("172.19.17.10"), None, None, RuntimeError("unreachable")),
        (_sw("172.19.17.11"), SwitchPollInfo(is_online=True), None, None),
        (_sw("172.19.17.12"), SwitchPollInfo(is_online=True), None, None),
        (_sw("172.19.17.13"), SwitchPollInfo(is_online=True), None, None),
    ]

    assert _subnets_with_total_failure(results) == set()


def test_a_lone_switch_failing_is_never_treated_as_a_path_problem(monkeypatch) -> None:
    monkeypatch.setattr("app.domains.inventory.switch_polling.settings.POLL_PATH_FAILURE_MIN_DEVICES", 3)
    monkeypatch.setattr("app.domains.inventory.switch_polling.settings.POLL_PATH_FAILURE_RATIO", 0.8)

    results = [(_sw("172.19.17.10"), None, None, RuntimeError("unreachable"))]

    assert _subnets_with_total_failure(results) == set()


def test_switch_subnets_are_judged_independently(monkeypatch) -> None:
    monkeypatch.setattr("app.domains.inventory.switch_polling.settings.POLL_PATH_FAILURE_MIN_DEVICES", 3)
    monkeypatch.setattr("app.domains.inventory.switch_polling.settings.POLL_PATH_FAILURE_RATIO", 0.8)

    results = [
        (_sw("172.19.17.10"), None, None, RuntimeError("unreachable")),
        (_sw("172.19.17.11"), None, None, RuntimeError("unreachable")),
        (_sw("172.19.17.12"), None, None, RuntimeError("unreachable")),
        (_sw("172.19.18.10"), SwitchPollInfo(is_online=True), None, None),
        (_sw("172.19.18.11"), SwitchPollInfo(is_online=True), None, None),
        (_sw("172.19.18.12"), SwitchPollInfo(is_online=True), None, None),
    ]

    assert _subnets_with_total_failure(results) == {"172.19.17"}


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
    monkeypatch.setattr(
        "app.domains.inventory.switch_polling._fetch_switch_mac", lambda _switch: "aa:bb:cc:dd:ee:ff"
    )

    polled_switch, info, mac, exc = await poll_one_switch(switch)

    assert polled_switch is switch
    assert exc is None
    assert mac == "aa:bb:cc:dd:ee:ff"
    assert info == SwitchPollInfo(is_online=True, hostname="SW-CORE-01")
