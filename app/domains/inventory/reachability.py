from __future__ import annotations

import socket
from collections.abc import Callable
from dataclasses import dataclass

from app.services.hostname_resolver import resolve_hostname as resolve_hostname_with_fallback


@dataclass(frozen=True)
class ReachabilityResult:
    is_online: bool
    reason: str | None = None
    resolved_address: str | None = None


def resolve_hostname(hostname: str, *, dns_search_suffixes: str = "", dns_server: str = "") -> str | None:
    return resolve_hostname_with_fallback(
        hostname,
        dns_search_suffixes=dns_search_suffixes,
        dns_server=dns_server,
    )


def probe_host_ports(
    hostname: str,
    *,
    ports: tuple[int, ...],
    timeout: float,
    dns_search_suffixes: str = "",
    dns_server: str = "",
    port_checker: Callable[[str, int, float], bool] | None = None,
) -> ReachabilityResult:
    resolved_address = resolve_hostname(
        hostname,
        dns_search_suffixes=dns_search_suffixes,
        dns_server=dns_server,
    )
    if not resolved_address:
        return ReachabilityResult(is_online=False, reason="dns_unresolved")

    checker = port_checker or _socket_port_checker
    for port in ports:
        if checker(resolved_address, port, timeout):
            return ReachabilityResult(is_online=True, resolved_address=resolved_address)
    return ReachabilityResult(is_online=False, reason="port_closed", resolved_address=resolved_address)


def _socket_port_checker(address: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((address, port), timeout=timeout):
            return True
    except OSError:
        return False
