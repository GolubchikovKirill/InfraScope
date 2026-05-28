from __future__ import annotations

import struct

from app.domains.inventory import reachability
from app.services import hostname_resolver


def test_resolve_hostname_tries_dns_search_suffix(monkeypatch) -> None:
    calls: list[str] = []

    def fake_gethostbyname(hostname: str) -> str:
        calls.append(hostname)
        if hostname == "workstation.example.local":
            return "10.10.1.15"
        raise OSError

    monkeypatch.setattr(reachability.socket, "gethostbyname", fake_gethostbyname)

    result = reachability.resolve_hostname("workstation", dns_search_suffixes="example.local")

    assert result == "10.10.1.15"
    assert calls == ["workstation", "workstation.example.local"]


def test_probe_host_ports_returns_online_on_first_open_port(monkeypatch) -> None:
    monkeypatch.setattr(reachability.socket, "gethostbyname", lambda _hostname: "10.10.1.20")
    checked: list[int] = []

    def fake_checker(_address: str, port: int, _timeout: float) -> bool:
        checked.append(port)
        return port == 3389

    result = reachability.probe_host_ports(
        "cash-01",
        ports=(445, 3389),
        timeout=1.5,
        port_checker=fake_checker,
    )

    assert result.is_online is True
    assert result.reason is None
    assert result.resolved_address == "10.10.1.20"
    assert checked == [445, 3389]


def test_probe_host_ports_reports_dns_failure(monkeypatch) -> None:
    def fake_gethostbyname(_hostname: str) -> str:
        raise OSError

    monkeypatch.setattr(reachability.socket, "gethostbyname", fake_gethostbyname)

    result = reachability.probe_host_ports("missing-host", ports=(445,), timeout=1.0)

    assert result.is_online is False
    assert result.reason == "dns_unresolved"


def test_probe_host_ports_reports_closed_ports(monkeypatch) -> None:
    monkeypatch.setattr(reachability.socket, "gethostbyname", lambda _hostname: "10.10.1.30")

    result = reachability.probe_host_ports(
        "closed-host",
        ports=(445, 3389),
        timeout=1.0,
        port_checker=lambda _address, _port, _timeout: False,
    )

    assert result.is_online is False
    assert result.reason == "port_closed"
    assert result.resolved_address == "10.10.1.30"


def test_resolve_hostname_returns_ip_literal() -> None:
    assert reachability.resolve_hostname("10.10.1.44") == "10.10.1.44"


def test_resolve_hostname_uses_explicit_dns_server(monkeypatch) -> None:
    hostname_resolver._RESOLVE_CACHE.clear()
    monkeypatch.setattr(reachability.socket, "gethostbyname", lambda _hostname: (_ for _ in ()).throw(OSError()))

    query_payload = b""

    class DummySocket:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def settimeout(self, _timeout: float) -> None:
            return None

        def sendto(self, payload: bytes, _target: tuple[str, int]) -> int:
            nonlocal query_payload
            query_payload = payload
            return len(payload)

        def recvfrom(self, _size: int) -> tuple[bytes, tuple[str, int]]:
            transaction_id = query_payload[:2]
            header = transaction_id + struct.pack(">HHHHH", 0x8180, 1, 1, 0, 0)
            question = query_payload[12:]
            answer = b"\xc0\x0c" + struct.pack(">HHIH", 1, 1, 60, 4) + bytes([10, 10, 1, 77])
            return header + question + answer, ("10.10.1.1", 53)

    monkeypatch.setattr(hostname_resolver.socket, "socket", DummySocket)

    resolved = reachability.resolve_hostname(
        "workstation",
        dns_search_suffixes="example.local",
        dns_server="10.10.1.1",
    )

    assert resolved == "10.10.1.77"


def test_resolve_hostname_uses_hosts_file(monkeypatch, tmp_path) -> None:
    hostname_resolver._RESOLVE_CACHE.clear()
    hosts_file = tmp_path / "hosts"
    hosts_file.write_text("10.10.1.88 cash-01 cash-01.example.local\n", encoding="utf-8")

    monkeypatch.setattr(reachability.socket, "gethostbyname", lambda _hostname: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(hostname_resolver, "_HOSTS_PATH", hosts_file)

    resolved = reachability.resolve_hostname("cash-01")

    assert resolved == "10.10.1.88"
