from __future__ import annotations

from ._pysnmp_compat import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    get_cmd,
    walk_cmd,
)


def _decode_snmp_value(val) -> str:
    """Decode SNMP value, handling UTF-8 encoded OctetStrings correctly."""
    if hasattr(val, "asOctets"):
        raw = val.asOctets()
        try:
            return raw.decode("utf-8")
        except (UnicodeDecodeError, ValueError):
            pass
        try:
            return raw.decode("latin-1")
        except (UnicodeDecodeError, ValueError):
            pass
    return str(val)


async def _snmp_get(
    engine: SnmpEngine,
    target: UdpTransportTarget,
    community: CommunityData,
    oid: str,
) -> str | None:
    error_indication, error_status, _error_index, var_binds = await get_cmd(
        engine,
        community,
        target,
        ContextData(),
        ObjectType(ObjectIdentity(oid)),
    )
    if error_indication or error_status:
        return None
    for _oid, val in var_binds:
        return _decode_snmp_value(val)
    return None


async def _snmp_walk(
    engine: SnmpEngine,
    target: UdpTransportTarget,
    community: CommunityData,
    oid: str,
) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    async for error_indication, error_status, _error_index, var_binds in walk_cmd(
        engine,
        community,
        target,
        ContextData(),
        ObjectType(ObjectIdentity(oid)),
        lexicographicMode=False,
    ):
        if error_indication or error_status:
            break
        for oid_result, val in var_binds:
            results.append((str(oid_result), _decode_snmp_value(val)))
    return results
