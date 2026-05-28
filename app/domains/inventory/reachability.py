from __future__ import annotations

import ipaddress
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter

from app.core.config import settings
from app.observability.metrics import network_probe_attempts_total, network_probe_duration_seconds
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


def build_dns_search_suffixes(dns_search_suffixes: str, fallback_domain: str = "") -> str:
    explicit = dns_search_suffixes.strip()
    if explicit:
        return explicit
    candidate = fallback_domain.strip().strip(".")
    if not candidate:
        return ""
    try:
        ipaddress.ip_address(candidate)
        return ""
    except ValueError:
        return candidate if "." in candidate else ""


def probe_host_ports(
    hostname: str,
    *,
    ports: tuple[int, ...],
    timeout: float,
    probe_scope: str = "generic",
    max_attempts: int | None = None,
    retry_backoff_seconds: float | None = None,
    timeout_multiplier: float | None = None,
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
    attempts = max(1, max_attempts if max_attempts is not None else settings.NETWORK_PROBE_MAX_ATTEMPTS)
    backoff = max(0.0, retry_backoff_seconds if retry_backoff_seconds is not None else settings.NETWORK_PROBE_RETRY_BACKOFF_SECONDS)
    timeout_scale = max(
        1.0,
        timeout_multiplier if timeout_multiplier is not None else settings.NETWORK_PROBE_TIMEOUT_MULTIPLIER,
    )
    for port in ports:
        for attempt_idx in range(attempts):
            attempt_timeout = timeout * (timeout_scale**attempt_idx)
            started = perf_counter()
            try:
                if checker(resolved_address, port, attempt_timeout):
                    network_probe_attempts_total.labels(scope=probe_scope, result="success").inc()
                    network_probe_duration_seconds.labels(scope=probe_scope, result="success").observe(
                        max(perf_counter() - started, 0)
                    )
                    return ReachabilityResult(is_online=True, resolved_address=resolved_address)
            except Exception:
                network_probe_attempts_total.labels(scope=probe_scope, result="error").inc()
                network_probe_duration_seconds.labels(scope=probe_scope, result="error").observe(
                    max(perf_counter() - started, 0)
                )
            else:
                network_probe_attempts_total.labels(scope=probe_scope, result="closed").inc()
                network_probe_duration_seconds.labels(scope=probe_scope, result="closed").observe(
                    max(perf_counter() - started, 0)
                )
            if attempt_idx < attempts - 1 and backoff > 0:
                time.sleep(backoff * (attempt_idx + 1))
    return ReachabilityResult(is_online=False, reason="port_closed", resolved_address=resolved_address)


def _socket_port_checker(address: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((address, port), timeout=timeout):
            return True
    except OSError:
        return False
