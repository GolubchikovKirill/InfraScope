from __future__ import annotations

from sqlmodel import select

from app.core.config import settings
from app.domains.inventory import network_discovery
from app.domains.inventory.models import Computer

# a slice of the real regstaer-m.local zone
_ZONE = {
    "VNA-TV-101": "172.23.8.81",
    "vna-tv-1101": "10.10.98.146",
    "vna-tv-1301": "172.23.4.5",
    "vna-tv-606": "10.10.99.129",
    "vna-kkm-1506": "10.10.98.20",
    "VNA-MUZ-901": "10.10.99.30",
    "DomainDnsZones": "10.10.98.41",
}


def test_role_of_reads_the_middle_token() -> None:
    assert network_discovery.role_of("vna-tv-1301") == "TV"
    assert network_discovery.role_of("VNA-KKM-1506") == "KKM"
    assert network_discovery.role_of("HPIF74BC9") is None


def test_zone_defaults_to_the_first_search_suffix(monkeypatch) -> None:
    monkeypatch.setattr(settings, "DNS_DISCOVERY_ZONE", "")
    monkeypatch.setattr(settings, "DNS_SEARCH_SUFFIXES", "regstaer-m.local, regstaer.local")
    assert network_discovery.discovery_zone() == "regstaer-m.local"
    monkeypatch.setattr(settings, "DNS_DISCOVERY_ZONE", "other.local.")
    assert network_discovery.discovery_zone() == "other.local"


def test_adds_only_missing_machines_of_the_discovered_roles(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "DNS_DISCOVERY_ROLES", "TV")
    db_session.add(Computer(hostname="VNA-TV-1101"))
    db_session.add(Computer(hostname="vna-tv-101"))
    db_session.commit()

    result = network_discovery.discover_computers_from_dns(db_session, records=_ZONE)

    assert result.matched == 4
    assert result.added == ["VNA-TV-1301", "VNA-TV-606"]
    hostnames = sorted(db_session.exec(select(Computer.hostname)).all())
    assert hostnames == ["VNA-TV-1101", "VNA-TV-1301", "VNA-TV-606", "vna-tv-101"]


def test_running_twice_adds_nothing_new(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "DNS_DISCOVERY_ROLES", "TV")
    network_discovery.discover_computers_from_dns(db_session, records=_ZONE)

    again = network_discovery.discover_computers_from_dns(db_session, records=_ZONE)

    assert again.added == []


def test_no_roles_means_no_discovery(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "DNS_DISCOVERY_ROLES", "")

    assert network_discovery.discover_computers_from_dns(db_session, records=_ZONE).added == []
