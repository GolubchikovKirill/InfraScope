from app.services.scanner import _parse_ports, _parse_subnets


def test_parse_subnets_supports_multiple_cidrs():
    ips = _parse_subnets("10.0.0.0/30,10.0.1.0/30")
    # /30 has two host addresses per subnet
    assert "10.0.0.1" in ips
    assert "10.0.0.2" in ips
    assert "10.0.1.1" in ips
    assert "10.0.1.2" in ips


def test_parse_subnets_ignores_invalid_entries():
    ips = _parse_subnets("invalid,10.10.10.0/30")
    assert ips == ["10.10.10.1", "10.10.10.2"]


def test_parse_ports_filters_invalid_and_deduplicates():
    ports = _parse_ports("9100, 631, not-a-port, 9100, 70000, 0")
    assert ports == [9100, 631]
