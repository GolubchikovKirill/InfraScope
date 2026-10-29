"""A development stack must not act on real equipment unless told to.

It sits in the same network as the stores; with a copied .env it would reboot
the same access points prod does, and the two instances' locks know nothing
about each other.
"""

from __future__ import annotations

import logging
import uuid

import pytest
from fastapi import HTTPException

from app.api.routes.switches import _shared
from app.core import safety
from app.core.config import Settings

PROD = {"ENVIRONMENT": "production", "SECRET_KEY": "k" * 40, "FIRST_SUPERUSER_PASSWORD": "Very-Strong-Pass-1"}


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch):
    # conftest allows writes for the rest of the suite; these tests decide for themselves
    monkeypatch.delenv("ALLOW_HARDWARE_WRITES", raising=False)


def test_outside_production_the_automations_are_switched_off() -> None:
    s = Settings(
        ENVIRONMENT="development", AUTO_REBOOT_AP_ENABLED=True, DHCP_CLEAR_ENABLED=True, REMOTE_ACCESS_ENABLED=True
    )

    assert s.hardware_writes_allowed is False
    assert (s.AUTO_REBOOT_AP_ENABLED, s.DHCP_CLEAR_ENABLED, s.REMOTE_ACCESS_ENABLED) == (False, False, False)
    assert s.hardware_writes_disabled == ["AUTO_REBOOT_AP_ENABLED", "DHCP_CLEAR_ENABLED", "REMOTE_ACCESS_ENABLED"]


def test_production_keeps_them_as_configured() -> None:
    s = Settings(**PROD, AUTO_REBOOT_AP_ENABLED=True, DHCP_CLEAR_ENABLED=True)

    assert s.hardware_writes_allowed is True
    assert s.AUTO_REBOOT_AP_ENABLED is True and s.DHCP_CLEAR_ENABLED is True
    assert s.hardware_writes_disabled == []


def test_the_explicit_setting_wins_either_way() -> None:
    lab = Settings(ENVIRONMENT="development", ALLOW_HARDWARE_WRITES=True, AUTO_REBOOT_AP_ENABLED=True)
    frozen_prod = Settings(**PROD, ALLOW_HARDWARE_WRITES=False, AUTO_REBOOT_AP_ENABLED=True)

    assert lab.AUTO_REBOOT_AP_ENABLED is True
    assert frozen_prod.AUTO_REBOOT_AP_ENABLED is False


@pytest.mark.asyncio
async def test_manual_switch_writes_are_refused_before_any_lock_or_ssh(monkeypatch) -> None:
    monkeypatch.setattr(_shared, "settings", Settings(ENVIRONMENT="development"))

    async def _must_not_touch_redis():
        raise AssertionError("the guard must refuse before taking the lease")

    monkeypatch.setattr(_shared, "get_redis", _must_not_touch_redis)

    with pytest.raises(HTTPException) as exc:
        await _shared._acquire_switch_write_lock(uuid.uuid4())

    assert exc.value.status_code == 403
    assert "ALLOW_HARDWARE_WRITES" in exc.value.detail


def test_the_startup_log_names_what_was_switched_off(monkeypatch, caplog) -> None:
    monkeypatch.setattr(safety, "settings", Settings(ENVIRONMENT="development", AUTO_REBOOT_AP_ENABLED=True))

    with caplog.at_level(logging.WARNING):
        safety.log_hardware_write_guard(logging.getLogger("test"), "worker")

    assert "hardware writes are disabled" in caplog.text
    assert "AUTO_REBOOT_AP_ENABLED" in caplog.text


def test_production_logs_nothing(monkeypatch, caplog) -> None:
    monkeypatch.setattr(safety, "settings", Settings(**PROD))

    with caplog.at_level(logging.WARNING):
        safety.log_hardware_write_guard(logging.getLogger("test"), "worker")

    assert caplog.text == ""
