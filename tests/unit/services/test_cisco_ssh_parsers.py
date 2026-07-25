from app.services.cisco_ssh import (
    _enrich_mac_from_table,
    _normalize_port,
    _parse_cdp_access_points,
    parse_interface_status_table,
)


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


def test_parse_interface_status_table_keeps_ports_with_no_description():
    # Real "show interfaces status" output: the Name column is fixed-width
    # but empty for most ports. Counting whitespace-split tokens from the
    # end of the line (the historical bug) gives a port with no name one
    # fewer token than a described one and silently drops it.
    output = (
        "Port      Name               Status       Vlan       Duplex  Speed Type\n"
        "Gi2/0/14                     connected    247        a-full  a-100 10/100/1000BaseTX\n"
        "Gi3/0/1   Camera-Entrance    connected    244        a-full  a-100 10/100/1000BaseTX\n"
        "Gi2/0/20                     notconnect   1          auto    auto  10/100/1000BaseTX\n"
    )

    rows = parse_interface_status_table(output)

    assert [r.port for r in rows] == ["Gi2/0/14", "Gi3/0/1", "Gi2/0/20"]
    assert rows[0].name is None
    assert rows[0].vlan_text == "247"
    assert rows[0].status == "connected"
    assert rows[1].name == "Camera-Entrance"
    assert rows[1].vlan_text == "244"
    assert rows[2].name is None
    assert rows[2].status == "notconnect"
    assert rows[2].vlan_text == "1"
