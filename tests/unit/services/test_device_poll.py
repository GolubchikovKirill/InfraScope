from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from app.services import device_poll


class _Writer:
    def close(self) -> None:
        pass

    async def wait_closed(self) -> None:
        return None


def test_poll_device_sync_supports_multiple_temporary_event_loops(monkeypatch) -> None:
    """Regression test for Semaphore bound to a different event loop.

    Synchronous callers create a fresh loop per worker thread.  The port scan
    limit must be loop-local in that mode rather than a module-global asyncio
    primitive bound to the first worker.
    """

    async def _open_connection(_ip: str, _port: int):
        return object(), _Writer()

    async def _empty_snmp(*_args, **_kwargs):
        return {}

    async def _empty_mac(*_args, **_kwargs):
        return None

    async def _no_ping(*_args, **_kwargs) -> bool:
        return False

    monkeypatch.setattr(device_poll, "_resolve_host", lambda address: address)
    monkeypatch.setattr(device_poll.asyncio, "open_connection", _open_connection)
    monkeypatch.setattr(device_poll, "_get_snmp_info", _empty_snmp)
    monkeypatch.setattr(device_poll, "_get_snmp_mac", _empty_mac)
    monkeypatch.setattr(device_poll, "_get_mac_from_arp", lambda _ip: None)
    monkeypatch.setattr(device_poll, "_icmp_ping", _no_ping)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(device_poll.poll_device_sync, [f"10.10.10.{i}" for i in range(20, 24)]))

    assert all(result.is_online for result in results)


def test_poll_device_online_via_ping_when_no_ports_or_snmp(monkeypatch) -> None:
    """A locked-down nettop with no open ports and no SNMP still answers ping."""

    async def _closed_ports(_ip: str, *, semaphore=None) -> list[int]:
        return []

    async def _empty_snmp(*_args, **_kwargs) -> dict:
        return {}

    async def _empty_mac(*_args, **_kwargs) -> str | None:
        return None

    async def _ping_ok(_ip: str) -> bool:
        return True

    monkeypatch.setattr(device_poll, "_resolve_host", lambda address: address)
    monkeypatch.setattr(device_poll, "_scan_ports", _closed_ports)
    monkeypatch.setattr(device_poll, "_get_snmp_info", _empty_snmp)
    monkeypatch.setattr(device_poll, "_get_snmp_mac", _empty_mac)
    monkeypatch.setattr(device_poll, "_get_mac_from_arp", lambda _ip: None)
    monkeypatch.setattr(device_poll, "_icmp_ping", _ping_ok)

    status = asyncio.run(device_poll.poll_device("10.10.10.50"))

    assert status.is_online is True
    assert status.open_ports == []


def test_poll_device_offline_when_ports_snmp_and_ping_all_fail(monkeypatch) -> None:
    async def _closed_ports(_ip: str, *, semaphore=None) -> list[int]:
        return []

    async def _empty_snmp(*_args, **_kwargs) -> dict:
        return {}

    async def _empty_mac(*_args, **_kwargs) -> str | None:
        return None

    async def _ping_fail(_ip: str) -> bool:
        return False

    monkeypatch.setattr(device_poll, "_resolve_host", lambda address: address)
    monkeypatch.setattr(device_poll, "_scan_ports", _closed_ports)
    monkeypatch.setattr(device_poll, "_get_snmp_info", _empty_snmp)
    monkeypatch.setattr(device_poll, "_get_snmp_mac", _empty_mac)
    monkeypatch.setattr(device_poll, "_get_mac_from_arp", lambda _ip: None)
    monkeypatch.setattr(device_poll, "_icmp_ping", _ping_fail)

    status = asyncio.run(device_poll.poll_device("10.10.10.51"))

    assert status.is_online is False


def test_icmp_ping_false_when_binary_missing(monkeypatch) -> None:
    async def _missing_binary(*_args, **_kwargs):
        raise FileNotFoundError("ping: not found")

    monkeypatch.setattr(device_poll.asyncio, "create_subprocess_exec", _missing_binary)

    assert asyncio.run(device_poll._icmp_ping("10.10.10.52")) is False

