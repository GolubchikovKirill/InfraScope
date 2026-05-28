from datetime import UTC, datetime

from sqlmodel import Session, select

from app.core.config import settings
from app.domains.operations.models import AppSetting

GENERAL_SETTINGS_KEYS = {
    "scan_subnet",
    "scan_ports",
    "dns_search_suffixes",
}


def _default_general_settings() -> dict[str, str]:
    return {
        "scan_subnet": settings.SCAN_SUBNET,
        "scan_ports": settings.SCAN_PORTS,
        "dns_search_suffixes": settings.DNS_SEARCH_SUFFIXES or "",
    }


def get_general_settings(session: Session) -> dict[str, str]:
    defaults = _default_general_settings()
    rows = session.exec(select(AppSetting).where(AppSetting.key.in_(GENERAL_SETTINGS_KEYS))).all()
    for row in rows:
        defaults[row.key] = row.value
    return defaults


def update_general_settings(session: Session, values: dict[str, str]) -> dict[str, str]:
    normalized = {k: v for k, v in values.items() if k in GENERAL_SETTINGS_KEYS}
    if not normalized:
        return get_general_settings(session)

    existing = {
        row.key: row
        for row in session.exec(select(AppSetting).where(AppSetting.key.in_(list(normalized.keys())))).all()
    }
    now = datetime.now(UTC)
    for key, value in normalized.items():
        row = existing.get(key)
        if row is None:
            row = AppSetting(key=key, value=value, updated_at=now)
        else:
            row.value = value
            row.updated_at = now
        session.add(row)
    session.commit()
    return get_general_settings(session)
