from __future__ import annotations

from datetime import UTC, datetime

from app.domains.operations.models import EventLog
from app.services.kafka_events import publish_event

_SEVERITIES = {"info", "warning", "error", "critical"}


def _current_trace_id() -> str | None:
    try:
        from opentelemetry import trace
    except Exception:
        return None
    span = trace.get_current_span()
    if span is None:
        return None
    trace_id = span.get_span_context().trace_id
    if not trace_id:
        return None
    return f"{trace_id:032x}"


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
    publish_event(
        {
            "id": str(event.id),
            "trace_id": _current_trace_id(),
            "severity": event.severity,
            "category": event.category,
            "event_type": event.event_type,
            "message": event.message,
            "device_kind": event.device_kind,
            "device_name": event.device_name,
            "ip_address": event.ip_address,
            "created_at": (event.created_at or datetime.now(UTC)).isoformat(),
        }
    )
