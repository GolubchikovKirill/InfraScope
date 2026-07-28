from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.domains.inventory.ap_registry import recover_missing_macs_from_registry
from app.domains.inventory.models import SwitchAccessPoint
from app.services.cisco_ssh import APInfo


def _known_row(port: str, mac: str, cdp_name: str) -> SwitchAccessPoint:
    return SwitchAccessPoint(
        switch_id=uuid.uuid4(),
        port=port,
        mac_address=mac,
        cdp_name=cdp_name,
        last_seen_at=datetime.now(UTC),
    )


def test_recovers_mac_when_port_and_cdp_name_match_a_known_row():
    # Real case from A30: CDP found "AP_A6_VS" on Gi1/0/28 every time, but
    # the switch's MAC address table entry for that port was intermittently
    # stale, leaving mac_address empty on some scans.
    live = [APInfo(mac_address="", port="GigabitEthernet1/0/28", vlan=20, cdp_name="AP_A6_VS")]
    known = [_known_row("GigabitEthernet1/0/28", "54:75:d0:b7:da:ec", "AP_A6_VS")]

    result = recover_missing_macs_from_registry(live, known)

    assert result[0].mac_address == "54:75:d0:b7:da:ec"


def test_does_not_recover_when_cdp_name_does_not_match():
    # A different device could occupy the same port later - matching on
    # port alone would risk misattributing it to the old known AP.
    live = [APInfo(mac_address="", port="GigabitEthernet1/0/28", vlan=20, cdp_name="AP_NEW_DEVICE")]
    known = [_known_row("GigabitEthernet1/0/28", "54:75:d0:b7:da:ec", "AP_A6_VS")]

    result = recover_missing_macs_from_registry(live, known)

    assert result[0].mac_address == ""


def test_does_not_override_an_already_resolved_mac():
    live = [APInfo(mac_address="ec:bd:1d:f9:7b:a0", port="GigabitEthernet1/0/34", vlan=20, cdp_name="APecbd.1df9.7ba0")]
    known = [_known_row("GigabitEthernet1/0/34", "aa:aa:aa:aa:aa:aa", "APecbd.1df9.7ba0")]

    result = recover_missing_macs_from_registry(live, known)

    assert result[0].mac_address == "ec:bd:1d:f9:7b:a0"


def test_leaves_unresolved_when_no_known_row_matches():
    live = [APInfo(mac_address="", port="GigabitEthernet1/0/99", vlan=20, cdp_name="AP_UNKNOWN")]

    result = recover_missing_macs_from_registry(live, known_rows=[])

    assert result[0].mac_address == ""
