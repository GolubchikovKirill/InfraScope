from __future__ import annotations

import re

from pydantic import BaseModel

_IP_PATTERN = r"^(\d{1,3}\.){3}\d{1,3}$"


def validate_ip_address(value: str) -> str:
    if not re.match(_IP_PATTERN, value):
        raise ValueError("Invalid IP address format")
    parts = value.split(".")
    if any(int(part) > 255 for part in parts):
        raise ValueError("IP address octets must be 0-255")
    return value


class Message(BaseModel):
    message: str
