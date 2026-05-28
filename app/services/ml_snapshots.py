from __future__ import annotations

from datetime import UTC, datetime

from app.domains.inventory.models import MediaPlayer, NetworkSwitch, Printer
from app.domains.ml.models import MLFeatureSnapshot


def _base_snapshot(
    *, device_kind: str, device_id, device_name: str | None, address: str | None, is_online: bool | None
):
    now = datetime.now(UTC)
    return {
        "device_kind": device_kind,
        "device_id": device_id,
        "device_name": device_name,
        "address": address,
        "is_online": is_online,
        "hour_of_day": now.hour,
        "day_of_week": now.weekday(),
        "captured_at": now,
    }


def write_printer_snapshots(session, printer: Printer, *, source: str = "poll") -> None:
    base = _base_snapshot(
        device_kind="printer",
        device_id=printer.id,
        device_name=printer.store_name,
        address=printer.ip_address or printer.host_pc,
        is_online=printer.is_online,
    )
    session.add(
        MLFeatureSnapshot(
            **base,
            source=source,
        )
    )
    for color, level, model in (
        ("black", printer.toner_black, printer.toner_black_name),
        ("cyan", printer.toner_cyan, printer.toner_cyan_name),
        ("magenta", printer.toner_magenta, printer.toner_magenta_name),
        ("yellow", printer.toner_yellow, printer.toner_yellow_name),
    ):
        if level is None:
            continue
        session.add(
            MLFeatureSnapshot(
                **base,
                source=source,
                toner_color=color,
                toner_level=level,
                toner_model=model,
            )
        )


def write_media_player_snapshot(session, player: MediaPlayer, *, source: str = "poll") -> None:
    base = _base_snapshot(
        device_kind="media_player",
        device_id=player.id,
        device_name=player.name,
        address=player.ip_address or player.hostname,
        is_online=player.is_online,
    )
    session.add(MLFeatureSnapshot(**base, source=source))


def write_switch_snapshot(session, sw: NetworkSwitch, *, source: str = "poll") -> None:
    base = _base_snapshot(
        device_kind="switch",
        device_id=sw.id,
        device_name=sw.name,
        address=sw.ip_address or sw.hostname,
        is_online=sw.is_online,
    )
    session.add(MLFeatureSnapshot(**base, source=source))
