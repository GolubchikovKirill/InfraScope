from __future__ import annotations

import ipaddress
import random
import socket
import struct
from pathlib import Path

from app.core.bounded_cache import BoundedTTLCache

_RESOLVE_CACHE_TTL_SECONDS = 300.0
_RESOLVE_CACHE = BoundedTTLCache[tuple[str, str, str], str | None](
    maxsize=4096,
    ttl_seconds=_RESOLVE_CACHE_TTL_SECONDS,
)
_HOSTS_PATH = Path("/etc/hosts")


def resolve_hostname(
    hostname: str,
    *,
    dns_search_suffixes: str = "",
    dns_server: str = "",
) -> str | None:
    value = hostname.strip()
    if not value:
        return None

    cache_key = (value.lower(), dns_search_suffixes.strip().lower(), dns_server.strip())
    found, cached = _RESOLVE_CACHE.lookup(cache_key)
    if found:
        return cached

    try:
        ip = str(ipaddress.ip_address(value))
        _RESOLVE_CACHE.set(cache_key, ip)
        return ip
    except ValueError:
        pass

    candidates = _build_candidates(value, dns_search_suffixes=dns_search_suffixes)
    for candidate in candidates:
        resolved = _resolve_with_system_dns(candidate)
        if resolved:
            _RESOLVE_CACHE.set(cache_key, resolved)
            return resolved

    if dns_server.strip():
        for candidate in candidates:
            resolved = _resolve_with_explicit_dns_server(candidate, dns_server.strip())
            if resolved:
                _RESOLVE_CACHE.set(cache_key, resolved)
                return resolved

    for candidate in candidates:
        resolved = _resolve_from_hosts_file(candidate)
        if resolved:
            _RESOLVE_CACHE.set(cache_key, resolved)
            return resolved

    _RESOLVE_CACHE.set(cache_key, None)
    return None


def _build_candidates(hostname: str, *, dns_search_suffixes: str) -> list[str]:
    candidates = [hostname]
    if "." not in hostname:
        suffixes = [suffix.strip().strip(".") for suffix in dns_search_suffixes.split(",") if suffix.strip()]
        candidates.extend(f"{hostname}.{suffix}" for suffix in suffixes if suffix)
    seen: set[str] = set()
    deduped: list[str] = []
    for candidate in candidates:
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _resolve_with_system_dns(candidate: str) -> str | None:
    try:
        return socket.gethostbyname(candidate)
    except OSError:
        pass
    try:
        infos = socket.getaddrinfo(candidate, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
        for info in infos:
            address = info[4][0]
            if address:
                return address
    except OSError:
        pass
    return None


def _resolve_from_hosts_file(candidate: str) -> str | None:
    try:
        lines = _HOSTS_PATH.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None

    target = candidate.lower()
    short_target = target.split(".", 1)[0]
    for line in lines:
        body = line.split("#", 1)[0].strip()
        if not body:
            continue
        parts = body.split()
        if len(parts) < 2:
            continue
        raw_ip = parts[0]
        try:
            parsed_ip = str(ipaddress.ip_address(raw_ip))
        except ValueError:
            continue
        aliases = [alias.lower() for alias in parts[1:]]
        if target in aliases or short_target in aliases:
            return parsed_ip
    return None


def _resolve_with_explicit_dns_server(candidate: str, dns_server: str) -> str | None:
    dns_ip = dns_server.strip()
    if not dns_ip:
        return None
    try:
        dns_ip = str(ipaddress.ip_address(dns_ip))
    except ValueError:
        return None

    query = _build_dns_query(candidate)
    if not query:
        return None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(1.5)
            sock.sendto(query, (dns_ip, 53))
            payload, _ = sock.recvfrom(2048)
            return _parse_dns_a_record(payload)
    except OSError:
        return None


def _build_dns_query(hostname: str) -> bytes | None:
    labels = [label for label in hostname.split(".") if label]
    if not labels:
        return None
    try:
        qname = b"".join(len(label).to_bytes(1, "big") + label.encode("ascii") for label in labels) + b"\x00"
    except UnicodeEncodeError:
        return None
    transaction_id = random.randint(0, 65535)
    header = struct.pack(">HHHHHH", transaction_id, 0x0100, 1, 0, 0, 0)
    question = qname + struct.pack(">HH", 1, 1)  # A IN
    return header + question


def _parse_dns_a_record(payload: bytes) -> str | None:
    if len(payload) < 12:
        return None
    _, _, qdcount, ancount, _, _ = struct.unpack(">HHHHHH", payload[:12])
    if ancount == 0:
        return None

    offset = 12
    for _ in range(qdcount):
        offset = _skip_dns_name(payload, offset)
        if offset + 4 > len(payload):
            return None
        offset += 4

    for _ in range(ancount):
        offset = _skip_dns_name(payload, offset)
        if offset + 10 > len(payload):
            return None
        rtype, rclass, _, rdlength = struct.unpack(">HHIH", payload[offset : offset + 10])
        offset += 10
        if offset + rdlength > len(payload):
            return None
        rdata = payload[offset : offset + rdlength]
        offset += rdlength
        if rtype == 1 and rclass == 1 and rdlength == 4:
            return ".".join(str(b) for b in rdata)
    return None


def _skip_dns_name(payload: bytes, offset: int) -> int:
    while offset < len(payload):
        length = payload[offset]
        if length == 0:
            return offset + 1
        if (length & 0xC0) == 0xC0:
            return offset + 2
        offset += 1 + length
    return offset
