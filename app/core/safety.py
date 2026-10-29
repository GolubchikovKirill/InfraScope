"""Startup notice for the hardware-write guard (see Settings.ALLOW_HARDWARE_WRITES)."""

from __future__ import annotations

import logging

from app.core.config import settings


def log_hardware_write_guard(logger: logging.Logger, process: str) -> None:
    """Say loudly, once per process, that this instance will not touch equipment.

    A development stack that silently skips the AP reboot is fine; a production
    one that does it because ENVIRONMENT was left unset is an outage nobody
    notices until the APs hang - so the reason is always in the first lines of
    the log.
    """
    if settings.hardware_writes_allowed:
        return
    disabled = ", ".join(settings.hardware_writes_disabled) or "none were on"
    logger.warning(
        "%s: hardware writes are disabled (ENVIRONMENT=%s, ALLOW_HARDWARE_WRITES unset or false). "
        "Switched off: %s. Manual switch writes are refused too.",
        process,
        settings.ENVIRONMENT,
        disabled,
    )
