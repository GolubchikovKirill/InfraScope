"""TCP port check for label printers (Zebra etc.)."""

from __future__ import annotations

import socket

ZEBRA_RAW_PORT = 9100
DEFAULT_TIMEOUT = 2.0


def check_port(ip: str, port: int = ZEBRA_RAW_PORT, timeout: float = DEFAULT_TIMEOUT) -> bool:
    """Return True if the TCP port is open (printer is reachable)."""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except (OSError, TimeoutError):
        return False
