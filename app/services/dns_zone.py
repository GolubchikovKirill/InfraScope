"""Reading a whole DNS zone from the AD DNS server (AXFR).

Windows DNS allows zone transfers to the hosts it is told to, and the AD
zone is the one complete list of the domain's machines: every Windows box
registers its own A record and keeps it current across DHCP leases.
"""

from __future__ import annotations

import logging

import dns.exception
import dns.query
import dns.rdataclass
import dns.rdatatype
import dns.zone

logger = logging.getLogger(__name__)

_AXFR_TIMEOUT_SECONDS = 10.0


def zone_a_records(server: str, zone: str) -> dict[str, str]:
    """Hostname -> IPv4 for every A record in the zone, keyed by the name as
    registered (VNA-TV-101, vna-tv-1101: casing is whatever the machine sent).

    Empty when the transfer is refused or the server cannot be reached - the
    caller then simply finds nothing new.
    """
    origin = zone.strip().strip(".")
    if not server.strip() or not origin:
        return {}
    try:
        transferred = dns.zone.from_xfr(dns.query.xfr(server.strip(), origin, lifetime=_AXFR_TIMEOUT_SECONDS))
    except (dns.exception.DNSException, OSError, EOFError) as exc:
        logger.warning("Zone transfer of %s from %s failed: %s", origin, server, exc)
        return {}

    records: dict[str, str] = {}
    for name, node in transferred.nodes.items():
        label = name.to_text()
        if label == "@" or "." in label:
            continue
        rdataset = node.get_rdataset(dns.rdataclass.IN, dns.rdatatype.A)
        if rdataset:
            records[label] = next(iter(rdataset)).address
    return records
