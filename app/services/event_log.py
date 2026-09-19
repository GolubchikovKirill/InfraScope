from __future__ import annotations

from app.domains.operations.models import EventLog

_SEVERITIES = {"info", "warning", "error", "critical"}


def write_event_log(
    session,
    *,
    event_type: str,
    message: str,
    severity: str = "info",
    category: str = "system",
    device_kind: str | None = None,
    device_name: str | None = None,
    ip_address: str | None = None,
) -> None:
    level = severity.strip().lower()
    if level not in _SEVERITIES:
        level = "info"
    event = EventLog(
        severity=level,
        category=(category or "system")[:64],
        event_type=(event_type or "unknown")[:128],
        message=(message or "")[:1024],
        device_kind=(device_kind or None),
        device_name=(device_name or None),
        ip_address=(ip_address or None),
    )
    session.add(event)
