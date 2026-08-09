from __future__ import annotations

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

    monkeypatch.setattr(device_poll, "_resolve_host", lambda address: address)
    monkeypatch.setattr(device_poll.asyncio, "open_connection", _open_connection)
    monkeypatch.setattr(device_poll, "_get_snmp_info", _empty_snmp)
    monkeypatch.setattr(device_poll, "_get_snmp_mac", _empty_mac)
    monkeypatch.setattr(device_poll, "_get_mac_from_arp", lambda _ip: None)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(device_poll.poll_device_sync, [f"10.10.10.{i}" for i in range(20, 24)]))

    assert all(result.is_online for result in results)

