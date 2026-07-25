from __future__ import annotations

import re

from app.domains.shared.schemas import _IP_PATTERN, validate_ip_address

__all__ = ["_validate_ip", "_normalize_mac", "_HOSTNAME_PATTERN", "_validate_ip_or_hostname"]


def _validate_ip(v: str) -> str:
    return validate_ip_address(v)


def _normalize_mac(v: str | None) -> str | None:
    if v is None:
        return None
    compact = re.sub(r"[^0-9a-fA-F]", "", v.strip())
    if not compact:
        return None
    if not re.fullmatch(r"[0-9a-fA-F]{12}", compact):
        raise ValueError("mac_address must contain 12 hex digits")
    return ":".join(compact[i : i + 2].lower() for i in range(0, 12, 2))


_HOSTNAME_PATTERN = r"^[a-zA-Z0-9]([a-zA-Z0-9\-\.]{0,253}[a-zA-Z0-9])?$"


def _validate_ip_or_hostname(v: str) -> str:
    v = v.strip()
    if not v or len(v) > 255:
        raise ValueError("Address must be 1-255 characters")
    if re.match(_IP_PATTERN, v):
        parts = v.split(".")
        if any(int(p) > 255 for p in parts):
            raise ValueError("IP address octets must be 0-255")
        return v
    if re.match(_HOSTNAME_PATTERN, v):
        return v
    raise ValueError("Must be a valid IP address or hostname")
