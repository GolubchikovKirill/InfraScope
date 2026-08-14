from __future__ import annotations

import logging

from ._pysnmp_compat import CommunityData, SnmpEngine, UdpTransportTarget
from .helpers import _detect_color, _extract_supply_key, _is_toner_supply
from .oids import (
    BROTHER_COLOR_MAP,
    BROTHER_TONER_BASE,
    OID_COLORANT_VALUE,
    OID_MARKER_COLORANT_IDX,
    OID_MARKER_DESCR,
    OID_MARKER_LEVEL,
    OID_MARKER_MAX,
    OID_MARKER_TYPE,
    RICOH_SUPPLY_DESCR,
    RICOH_SUPPLY_LEVEL,
    TonerLevel,
)
from .primitives import _snmp_get, _snmp_walk

logger = logging.getLogger(__name__)


async def _get_standard_toners(
    engine: SnmpEngine,
    target: UdpTransportTarget,
    comm: CommunityData,
) -> list[TonerLevel]:
    """Standard Printer MIB (RFC 3805). Works on HP, Ricoh, Kyocera, Canon, Xerox, etc."""
    descriptions = await _snmp_walk(engine, target, comm, OID_MARKER_DESCR)

    # Fallback: if WALK returned nothing, try direct GETs on common indices.
    # Some HP printers block WALK but respond to individual GETs.
    if not descriptions:
        for dev_idx in (1, 2):
            for sup_idx in range(1, 9):
                oid = f"{OID_MARKER_DESCR}.{dev_idx}.{sup_idx}"
                val = await _snmp_get(engine, target, comm, oid)
                if val and val.strip():
                    descriptions.append((oid, val))
            if descriptions:
                break

    if not descriptions:
        return []

    types_raw = await _snmp_walk(engine, target, comm, OID_MARKER_TYPE)
    max_raw = await _snmp_walk(engine, target, comm, OID_MARKER_MAX)
    level_raw = await _snmp_walk(engine, target, comm, OID_MARKER_LEVEL)

    # If WALK worked for descriptions but not for levels, try GET fallback too
    if descriptions and not level_raw:
        for oid_d, _ in descriptions:
            key = _extract_supply_key(oid_d)
            level_oid = f"{OID_MARKER_LEVEL}.{key}"
            max_oid = f"{OID_MARKER_MAX}.{key}"
            type_oid = f"{OID_MARKER_TYPE}.{key}"
            lv = await _snmp_get(engine, target, comm, level_oid)
            if lv is not None:
                level_raw.append((level_oid, lv))
            mv = await _snmp_get(engine, target, comm, max_oid)
            if mv is not None:
                max_raw.append((max_oid, mv))
            tv = await _snmp_get(engine, target, comm, type_oid)
            if tv is not None:
                types_raw.append((type_oid, tv))

    # Colorant-based color detection (Ricoh, some Canon/Xerox):
    # prtMarkerSuppliesColorantIndex links supply → colorant index
    # prtMarkerColorantValue gives the actual color name ("black", "cyan", etc.)
    colorant_idx_raw = await _snmp_walk(engine, target, comm, OID_MARKER_COLORANT_IDX)
    colorant_val_raw = await _snmp_walk(engine, target, comm, OID_COLORANT_VALUE)

    types_map = {_extract_supply_key(oid): val for oid, val in types_raw}
    max_map = {_extract_supply_key(oid): val for oid, val in max_raw}
    level_map = {_extract_supply_key(oid): val for oid, val in level_raw}
    colorant_idx_map = {_extract_supply_key(oid): val for oid, val in colorant_idx_raw}

    # Build colorant index → color name lookup
    # OID: .43.12.1.1.4.{deviceIdx}.{colorantIdx} → value is color name
    colorant_by_idx: dict[str, str] = {}
    for oid_c, color_name in colorant_val_raw:
        parts = oid_c.rsplit(".", 2)
        if len(parts) >= 3:
            device_idx = parts[-2]
            colorant_idx = parts[-1]
            colorant_by_idx[f"{device_idx}.{colorant_idx}"] = color_name.lower().strip()

    toners: list[TonerLevel] = []
    for oid_d, desc in descriptions:
        key = _extract_supply_key(oid_d)
        device_idx = key.split(".")[0] if "." in key else "1"

        supply_type: int | None = None
        try:
            supply_type = int(types_map[key]) if key in types_map else None
        except (ValueError, TypeError):
            pass

        if not _is_toner_supply(desc, supply_type):
            logger.debug("Skipping non-toner supply: %r (type=%s)", desc, supply_type)
            continue

        try:
            max_val = int(max_map.get(key, 0))
        except (ValueError, TypeError):
            max_val = 0

        try:
            cur_val = int(level_map.get(key, 0))
        except (ValueError, TypeError):
            cur_val = 0

        if cur_val == -3:
            pct = -3
        elif cur_val < 0:
            pct = -2
        elif max_val > 0:
            pct = max(0, min(100, round(cur_val / max_val * 100)))
        else:
            pct = None

        # Color detection: try description first, then colorant OID
        color = _detect_color(desc)
        if not color:
            ci = colorant_idx_map.get(key)
            if ci:
                colorant_key = f"{device_idx}.{ci}"
                colorant_color = colorant_by_idx.get(colorant_key, "")
                if colorant_color:
                    color = _detect_color(colorant_color)
                    if not color and colorant_color in ("black", "cyan", "magenta", "yellow"):
                        color = colorant_color
        if not color and len(descriptions) == 1:
            # Monochrome printer with single supply — assume black
            color = "black"

        toners.append(
            TonerLevel(
                description=desc,
                color=color,
                level_pct=pct,
                max_capacity=max_val,
                current_level=cur_val,
            )
        )

    if descriptions and not toners:
        logger.info(
            "Found %d supply entries but all filtered out — descriptions: %s",
            len(descriptions),
            [(d, types_map.get(_extract_supply_key(o))) for o, d in descriptions],
        )

    return toners


async def _get_brother_toners(
    engine: SnmpEngine,
    target: UdpTransportTarget,
    comm: CommunityData,
) -> list[TonerLevel]:
    """Brother proprietary toner OIDs. Returns percentage directly (0-100)."""
    raw = await _snmp_walk(engine, target, comm, BROTHER_TONER_BASE)
    if not raw:
        return []

    toners: list[TonerLevel] = []
    for oid, val in raw:
        color_idx = oid.rsplit(".", 1)[-1]
        color = BROTHER_COLOR_MAP.get(color_idx)
        try:
            pct = max(0, min(100, int(val)))
        except (ValueError, TypeError):
            pct = None

        toners.append(
            TonerLevel(
                description=f"{color or 'unknown'} toner",
                color=color,
                level_pct=pct,
                max_capacity=100,
                current_level=pct if pct is not None else 0,
            )
        )
    return toners


async def _get_ricoh_toners(
    engine: SnmpEngine,
    target: UdpTransportTarget,
    comm: CommunityData,
    standard_toners: list[TonerLevel],
) -> list[TonerLevel]:
    """Try Ricoh proprietary OIDs to get precise levels when standard MIB returns -3."""
    level_raw = await _snmp_walk(engine, target, comm, RICOH_SUPPLY_LEVEL)
    if not level_raw:
        return standard_toners

    descr_raw = await _snmp_walk(engine, target, comm, RICOH_SUPPLY_DESCR)
    descr_map = {oid.rsplit(".", 1)[-1]: val for oid, val in descr_raw}

    ricoh_toners: list[TonerLevel] = []
    for oid, val in level_raw:
        idx = oid.rsplit(".", 1)[-1]
        desc = descr_map.get(idx, "")
        try:
            raw_val = int(val)
        except (ValueError, TypeError):
            continue

        # Ricoh private MIB also uses -3 = "some remaining"
        if raw_val == -3:
            pct = -3
        elif raw_val < 0:
            pct = -2
        else:
            pct = max(0, min(100, raw_val))

        color = _detect_color(desc)
        if not color and len(level_raw) == 1:
            color = "black"

        ricoh_toners.append(
            TonerLevel(
                description=desc or f"{color or 'unknown'} toner",
                color=color,
                level_pct=pct,
                max_capacity=100,
                current_level=raw_val if raw_val >= 0 else 0,
            )
        )

    # Only use Ricoh proprietary data if it has at least one precise level (>= 0)
    has_precise = any(t.level_pct is not None and t.level_pct >= 0 for t in ricoh_toners)
    if ricoh_toners and has_precise:
        logger.info(
            "Ricoh proprietary OIDs returned %d toner(s) with precise levels",
            len(ricoh_toners),
        )
        return ricoh_toners
    return standard_toners
