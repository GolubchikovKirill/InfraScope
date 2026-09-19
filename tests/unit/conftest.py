from __future__ import annotations

import ipaddress
import socket

import pytest

_real_getaddrinfo = socket.getaddrinfo


def _offline_getaddrinfo(host, *args, **kwargs):
    """Unit tests must never wait on a real resolver.

    Tests that exercise name resolution stub ``socket.gethostbyname`` for the
    hostnames they care about, but the resolver falls back to
    ``socket.getaddrinfo`` when that raises - which goes to the machine's real
    DNS and took 10-18 s per call on a corporate resolver, making a handful of
    tests account for half of the suite's runtime. IP literals and loopback
    still work; any other name fails the way an unresolvable one does.
    """
    if host in (None, "", "localhost"):
        return _real_getaddrinfo(host, *args, **kwargs)
    try:
        ipaddress.ip_address(host)
    except ValueError:
        raise socket.gaierror(socket.EAI_NONAME, "name resolution disabled in unit tests") from None
    return _real_getaddrinfo(host, *args, **kwargs)


_real_gethostbyname = socket.gethostbyname


def _offline_gethostbyname(host):
    if host in ("", "localhost"):
        return _real_gethostbyname(host)
    try:
        ipaddress.ip_address(host)
    except ValueError:
        raise socket.gaierror(socket.EAI_NONAME, "name resolution disabled in unit tests") from None
    return _real_gethostbyname(host)


@pytest.fixture(autouse=True)
def _no_real_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    # Tests that need a specific name to resolve patch these themselves after
    # this fixture runs, so their own stubs still win.
    monkeypatch.setattr(socket, "getaddrinfo", _offline_getaddrinfo)
    monkeypatch.setattr(socket, "gethostbyname", _offline_gethostbyname)
