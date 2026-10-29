import asyncio

from app.services import device_poll

_HOST_ARP = """IP address       HW type     Flags       HW address            Mask     Device
10.10.98.222     0x1         0x2         00:e0:4c:62:e3:20     *        ens192
10.10.99.30      0x1         0x2         00:e0:4c:62:e3:20     *        ens192
10.10.98.1       0x1         0x0         00:00:00:00:00:00     *        ens192
"""


def _use_host_table(monkeypatch, tmp_path, text: str = _HOST_ARP) -> None:
    table = tmp_path / "arp"
    table.write_text(text)
    monkeypatch.setattr(device_poll, "_HOST_ARP_TABLE", str(table))
    real_read = device_poll._read_proc_arp
    # only the mounted host table: the test machine's own ARP and `ip neigh` stay out
    monkeypatch.setattr(device_poll, "_read_proc_arp", lambda path: real_read(path) if path == str(table) else [])
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: type("R", (), {"stdout": ""})())


def test_host_arp_table_is_read_and_incomplete_entries_dropped(monkeypatch, tmp_path) -> None:
    _use_host_table(monkeypatch, tmp_path)

    assert device_poll.arp_mac_for_ip("10.10.99.30") == "00:e0:4c:62:e3:20"
    assert device_poll.arp_mac_for_ip("10.10.98.1") is None


def test_stale_entry_at_the_recorded_address_does_not_count(monkeypatch, tmp_path) -> None:
    _use_host_table(monkeypatch, tmp_path)

    mac_map = device_poll._arp_table_mac_to_ip({"00:e0:4c:62:e3:20": "10.10.99.30"})

    assert mac_map == {"00:e0:4c:62:e3:20": "10.10.98.222"}


def test_find_devices_by_macs_skips_the_current_address(monkeypatch, tmp_path) -> None:
    _use_host_table(
        monkeypatch,
        tmp_path,
        "IP address HW type Flags HW address Mask Device\n10.10.98.222 0x1 0x2 00:e0:4c:62:e3:20 * ens192\n",
    )

    found = asyncio.run(
        device_poll.find_devices_by_macs(
            ["00:e0:4c:62:e3:20"], subnets=[], current_ips={"00:e0:4c:62:e3:20": "10.10.98.222"}
        )
    )

    # Only the address it left is known, and there is nothing to sweep: not found
    # (rather than "found where it already was", which ended the search before).
    assert found == {}
