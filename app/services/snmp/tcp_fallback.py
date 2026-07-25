from __future__ import annotations

import socket

_TCP_FALLBACK_PORTS = (80, 443, 9100, 631)
_TCP_TIMEOUT = 2.0


def _tcp_port_open(ip: str, port: int, timeout: float = _TCP_TIMEOUT) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except (OSError, TimeoutError):
        return False


def _tcp_reachable(ip: str) -> bool:
    """Check if any common printer port is open (HTTP, HTTPS, JetDirect, IPP)."""
    for port in _TCP_FALLBACK_PORTS:
        if _tcp_port_open(ip, port):
            return True
    return False
