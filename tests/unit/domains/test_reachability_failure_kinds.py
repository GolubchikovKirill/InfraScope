"""Why a probe failed, not just that it did.

These assertions are the contract the circuit breaker relies on: it backs off
only on `is_path_failure`. Calling a refused port a path failure would
silence a device that is up and answering; calling a dead route a refusal
would keep hammering a subnet that is gone.

The probe's happy paths, DNS resolution and retry behaviour are covered in
test_reachability.py - this file is only about the failure taxonomy.
"""

from __future__ import annotations

import errno
import socket

import pytest

from app.domains.inventory import reachability
from app.domains.inventory.reachability import (
    REASON_DNS_UNRESOLVED,
    REASON_NO_RESPONSE,
    REASON_NO_ROUTE,
    REASON_PORT_CLOSED,
    ReachabilityResult,
    probe_host_ports,
)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (ConnectionRefusedError(errno.ECONNREFUSED, "refused"), REASON_PORT_CLOSED),
        (TimeoutError("timed out"), REASON_NO_RESPONSE),
        # socket.timeout is an alias of TimeoutError, and both subclass
        # OSError - so the isinstance ordering in _classify_os_error matters.
        (socket.timeout("timed out"), REASON_NO_RESPONSE),
        (OSError(errno.EHOSTUNREACH, "no route to host"), REASON_NO_ROUTE),
        (OSError(errno.ENETUNREACH, "network unreachable"), REASON_NO_ROUTE),
        (OSError(errno.EPIPE, "unrelated"), REASON_NO_RESPONSE),
    ],
)
def test_socket_errors_are_classified(exc: OSError, expected: str) -> None:
    assert reachability._classify_os_error(exc) == expected


@pytest.mark.parametrize(
    ("reason", "is_path"),
    [
        (REASON_DNS_UNRESOLVED, True),
        (REASON_NO_ROUTE, True),
        # A refused port proves the host is alive.
        (REASON_PORT_CLOSED, False),
        # Ambiguous between a powered-off device and a black-holed path; one
        # socket cannot tell them apart, so it must not trip the breaker.
        (REASON_NO_RESPONSE, False),
        (None, False),
    ],
)
def test_only_infrastructure_failures_count_as_path_failures(reason: str | None, is_path: bool) -> None:
    assert ReachabilityResult(is_online=False, reason=reason).is_path_failure is is_path


def test_online_result_is_never_a_path_failure() -> None:
    assert ReachabilityResult(is_online=True).is_path_failure is False


def _resolves_to(monkeypatch, address: str | None) -> None:
    monkeypatch.setattr(reachability, "resolve_hostname", lambda *_a, **_kw: address)


def test_unresolvable_name_never_touches_the_network(monkeypatch) -> None:
    _resolves_to(monkeypatch, None)

    def _explode(*_args, **_kwargs):
        raise AssertionError("must not probe a name that does not resolve")

    monkeypatch.setattr(reachability, "_socket_port_probe", _explode)

    result = probe_host_ports("nowhere", ports=(445,), timeout=0.1)

    assert result.reason == REASON_DNS_UNRESOLVED
    assert result.is_path_failure is True


def test_no_route_abandons_the_remaining_ports(monkeypatch) -> None:
    """The other ports sit behind the same missing route, so probing them
    spends one timeout each to learn the same thing - which is what made a
    whole dead store slow to poll."""
    _resolves_to(monkeypatch, "10.0.0.6")
    tried: list[int] = []

    def _probe(_address: str, port: int, _timeout: float) -> str:
        tried.append(port)
        return REASON_NO_ROUTE

    monkeypatch.setattr(reachability, "_socket_port_probe", _probe)

    result = probe_host_ports("host", ports=(445, 3389, 135), timeout=0.1, max_attempts=3)

    assert result.reason == REASON_NO_ROUTE
    assert result.is_path_failure is True
    assert tried == [445], "gave up after the first port, without retrying it"


def test_last_failure_is_reported_once_every_port_is_tried(monkeypatch) -> None:
    _resolves_to(monkeypatch, "10.0.0.7")
    monkeypatch.setattr(
        reachability,
        "_socket_port_probe",
        lambda _a, port, _t: REASON_PORT_CLOSED if port == 445 else REASON_NO_RESPONSE,
    )

    result = probe_host_ports("host", ports=(445, 3389), timeout=0.1, max_attempts=1)

    assert result.reason == REASON_NO_RESPONSE
    assert result.is_path_failure is False


def test_each_retry_widens_the_timeout(monkeypatch) -> None:
    _resolves_to(monkeypatch, "10.0.0.8")
    timeouts: list[float] = []

    def _probe(_address: str, _port: int, timeout: float) -> str:
        timeouts.append(timeout)
        return REASON_NO_RESPONSE

    monkeypatch.setattr(reachability, "_socket_port_probe", _probe)

    probe_host_ports(
        "host",
        ports=(445,),
        timeout=1.0,
        max_attempts=3,
        retry_backoff_seconds=0.0,
        timeout_multiplier=2.0,
    )

    assert timeouts == [1.0, 2.0, 4.0]


def test_injected_bool_checker_cannot_fake_a_path_failure(monkeypatch) -> None:
    """Callers and tests inject a plain bool-returning checker. It cannot tell
    a refusal from a dead route, so its failures stay on the conservative
    REASON_PORT_CLOSED rather than being guessed into backing the poller off."""
    _resolves_to(monkeypatch, "10.0.0.9")

    result = probe_host_ports(
        "host",
        ports=(9100,),
        timeout=0.1,
        max_attempts=1,
        port_checker=lambda _a, _p, _t: False,
    )

    assert result.reason == REASON_PORT_CLOSED
    assert result.is_path_failure is False
