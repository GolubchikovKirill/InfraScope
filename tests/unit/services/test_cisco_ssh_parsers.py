from app.services.cisco_ssh import _enrich_mac_from_table, _normalize_port, _parse_cdp_access_points


def test_parse_cdp_access_points_filters_non_ap_entries():
    cdp_output = """
-------------------------
Device ID: AP-FLOOR-01
Interface: GigabitEthernet1/0/10, Port ID (outgoing port): GigabitEthernet0
Platform: cisco C9120AXI-R, Capabilities: Router Switch IGMP Trans-Bridge
IP address: 10.10.20.10
-------------------------
Device ID: CoreSwitch
Interface: GigabitEthernet1/0/1, Port ID (outgoing port): GigabitEthernet1/0/48
Platform: cisco WS-C2960X-48FPS-L, Capabilities: Switch IGMP
IP address: 10.10.20.1
"""
    aps = _parse_cdp_access_points(cdp_output, vlan=20)
    assert len(aps) == 1
    assert aps[0].cdp_name == "AP-FLOOR-01"
    assert aps[0].ip_address == "10.10.20.10"


def test_enrich_mac_from_table_matches_normalized_port_names():
    aps = _parse_cdp_access_points(
        """
-------------------------
Device ID: AP-FLOOR-01
Interface: GigabitEthernet1/0/10, Port ID (outgoing port): GigabitEthernet0
Platform: cisco C9120AXI-R, Capabilities: Router Switch IGMP Trans-Bridge
IP address: 10.10.20.10
""",
        vlan=20,
    )
    mac_output = " 20  aabb.ccdd.ee01   DYNAMIC  Gi1/0/10"
    _enrich_mac_from_table(aps, mac_output)
    assert aps[0].mac_address == "aa:bb:cc:dd:ee:01"
    assert _normalize_port("GigabitEthernet1/0/10") == "Gi1/0/10"
