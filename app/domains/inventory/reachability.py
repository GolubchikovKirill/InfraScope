"""One TCP reachability probe, shared by every device class.

Anything asking "is this box answering?" goes through `probe_host_ports`: it
resolves the name, retries with a widening timeout, records each attempt in
Prometheus, and reports *why* it failed.

The why is the point. "The port refused us" and "there is no route to that
subnet" both mean is_online=False, but one proves the host is alive and the
other says the path is gone. The circuit breaker and the device card each act
on that difference, so the probe has to preserve it rather than flatten
everything into a bool.
"""

from __future__ import annotations

import errno as errno_mod
import ipaddress
import logging
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter

from app.core.config import settings
from app.observability.metrics import network_probe_attempts_total, network_probe_duration_seconds
from app.services.hostname_resolver import resolve_hostname as resolve_hostname_with_fallback

logger = logging.getLogger(__name__)

#: The name does not resolve through DNS, the search suffixes, or /etc/hosts.
REASON_DNS_UNRESOLVED = "dns_unresolved"
#: TCP RST - the host is up and reachable, nothing is listening on that port.
REASON_PORT_CLOSED = "port_closed"
#: EHOSTUNREACH/ENETUNREACH - the network says it cannot get there at all.
REASON_NO_ROUTE = "no_route"
#: The connect timed out. Ambiguous: powered-off device or a black-holed path.
REASON_NO_RESPONSE = "no_response"
#: The probe itself raised something unexpected, not a verdict about the host.
REASON_PROBE_ERROR = "probe_error"

# Which failures mean "we never reached the device" as opposed to "the device
# answered and said no". Only these should make a circuit breaker back off.
_PATH_FAILURE_REASONS = frozenset({REASON_DNS_UNRESOLVED, REASON_NO_ROUTE})

_NO_ROUTE_ERRNOS = frozenset(
    code
    for code in (
        getattr(errno_mod, name, None)
        for name in ("EHOSTUNREACH", "ENETUNREACH", "ENETDOWN", "EHOSTDOWN")
    )
    if code is not None
)


@dataclass(frozen=True)
class ReachabilityResult:
    is_online: bool
    reason: str | None = None
    resolved_address: str | None = None

    @property
    def is_path_failure(self) -> bool:
        """True when the probe never got as far as the device.

        Feeds the circuit breaker's `probed_error`. A refused port proves the
        host is up and answering, so backing off from it would only delay
        noticing it recover - that is a device being off, not infrastructure
        breaking.

        A bare timeout is deliberately excluded. From one socket a
        powered-off printer and a dead uplink look identical, and counting
        every night-time printer as an infrastructure fault would open
        circuits across the whole fleet. Correlated subnet outages are
        detected separately, where there is enough evidence to tell.
        """
        return self.reason in _PATH_FAILURE_REASONS


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
    """Try each port in turn until one accepts; report the last failure seen.

    `port_checker` stays bool-returning for the callers and tests that inject
    one - an injected checker cannot distinguish refusal from a dead route, so
    its failures are reported as the conservative REASON_PORT_CLOSED.
    """
    resolved_address = resolve_hostname(
        hostname,
        dns_search_suffixes=dns_search_suffixes,
        dns_server=dns_server,
    )
    if not resolved_address:
        return ReachabilityResult(is_online=False, reason=REASON_DNS_UNRESOLVED)

    probe = _wrap_bool_checker(port_checker) if port_checker is not None else _socket_port_probe
    attempts = max(1, max_attempts if max_attempts is not None else settings.NETWORK_PROBE_MAX_ATTEMPTS)
    backoff = max(
        0.0,
        retry_backoff_seconds if retry_backoff_seconds is not None else settings.NETWORK_PROBE_RETRY_BACKOFF_SECONDS,
    )
    timeout_scale = max(
        1.0,
        timeout_multiplier if timeout_multiplier is not None else settings.NETWORK_PROBE_TIMEOUT_MULTIPLIER,
    )

    last_reason = REASON_NO_RESPONSE
    for port in ports:
        for attempt_idx in range(attempts):
            attempt_timeout = timeout * (timeout_scale**attempt_idx)
            started = perf_counter()
            try:
                failure = probe(resolved_address, port, attempt_timeout)
            except Exception as exc:
                logger.debug("Probe %s:%s raised %r", resolved_address, port, exc)
                _observe(probe_scope, REASON_PROBE_ERROR, started)
                last_reason = REASON_PROBE_ERROR
            else:
                if failure is None:
                    _observe(probe_scope, "success", started)
                    return ReachabilityResult(is_online=True, resolved_address=resolved_address)
                _observe(probe_scope, failure, started)
                last_reason = failure
                if failure == REASON_NO_ROUTE:
                    # The remaining ports sit behind the same missing route.
                    # Probing them spends one timeout each to learn the same
                    # thing, which is what makes a whole dead store slow to
                    # poll.
                    return ReachabilityResult(
                        is_online=False,
                        reason=REASON_NO_ROUTE,
                        resolved_address=resolved_address,
                    )
            if attempt_idx < attempts - 1 and backoff > 0:
                time.sleep(backoff * (attempt_idx + 1))

    return ReachabilityResult(is_online=False, reason=last_reason, resolved_address=resolved_address)


def probe_tcp_endpoint(
    address: str,
    *,
    port: int,
    timeout: float,
    probe_scope: str,
) -> ReachabilityResult:
    """Probe a device already known by IP - label printers, media players.

    A thin front for `probe_host_ports`; the resolver returns a literal IP
    unchanged, so this costs nothing extra and buys the retries, the metrics
    and the failure classification the old one-shot connect never had.
    """
    return probe_host_ports(address, ports=(port,), timeout=timeout, probe_scope=probe_scope)


def _observe(probe_scope: str, result: str, started: float) -> None:
    network_probe_attempts_total.labels(scope=probe_scope, result=result).inc()
    network_probe_duration_seconds.labels(scope=probe_scope, result=result).observe(max(perf_counter() - started, 0))


def _wrap_bool_checker(
    checker: Callable[[str, int, float], bool],
) -> Callable[[str, int, float], str | None]:
    def _probe(address: str, port: int, timeout: float) -> str | None:
        return None if checker(address, port, timeout) else REASON_PORT_CLOSED

    return _probe


def _socket_port_probe(address: str, port: int, timeout: float) -> str | None:
    """Return None when the port accepts, otherwise why it did not."""
    try:
        with socket.create_connection((address, port), timeout=timeout):
            return None
    except OSError as exc:
        return _classify_os_error(exc)


def _classify_os_error(exc: OSError) -> str:
    # TimeoutError covers socket.timeout, which is an alias for it, and both
    # are OSError subclasses - so this ordering matters.
    if isinstance(exc, TimeoutError):
        return REASON_NO_RESPONSE
    if isinstance(exc, ConnectionRefusedError):
        return REASON_PORT_CLOSED
    if exc.errno in _NO_ROUTE_ERRNOS:
        return REASON_NO_ROUTE
    return REASON_NO_RESPONSE
