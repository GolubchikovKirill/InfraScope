"""Inventory mirror: every cash register, computer and nettop media player becomes
a RemoteAccessDevice carrying the config that machine should end up with."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, or_
from sqlmodel import Session, select

from app.domains.inventory.models import Computer, MediaPlayer
from app.domains.operations.models import CashRegister
from app.domains.remote_access.models import RemoteAccessDevice

from .devices import (
    _NETTOP,
    _SOURCE_RANK,
    _get_or_create_device,
    _hostname_to_rid,
    _now,
    default_password,
    delete_device,
    mark_config_stale,
)


def _cr_location(cr: CashRegister) -> str | None:
    return cr.store_number or cr.store_code or None


def _inventory_maps(
    session: Session,
) -> tuple[dict[str, Computer], dict[str, CashRegister], dict[str, MediaPlayer]]:
    """One query per inventory table instead of one per device - built once by
    a caller that's about to _link_inventory a whole batch (seed_from_inventory,
    sync_from_console), not per row. Neither Computer.hostname's nor the
    others' index helps a lower(hostname) lookup (btree on the raw column,
    same class of gap the remoteaccessdevice one had - see migration
    a0b1c2d3e4f5), so a per-row query here was a real, avoidable seq scan
    times ~150 devices every 2-minute sync."""
    computers = {c.hostname.lower(): c for c in session.exec(select(Computer)).all() if c.hostname}
    registers = {c.hostname.lower(): c for c in session.exec(select(CashRegister)).all() if c.hostname}
    nettops = {
        m.hostname.lower(): m
        for m in session.exec(select(MediaPlayer).where(MediaPlayer.device_type == _NETTOP)).all()
        if m.hostname
    }
    return computers, registers, nettops


def _link_inventory(
    session: Session,
    dev: RemoteAccessDevice,
    *,
    computers: dict[str, Computer] | None = None,
    registers: dict[str, CashRegister] | None = None,
    nettops: dict[str, MediaPlayer] | None = None,
) -> None:
    """(Re)bind a device row to every inventory row that shares its hostname.

    Case-insensitive, same reasoning as _get_or_create_device - a device row
    minted from the console's self-reported hostname casing must still find
    its inventory row even when that row's own hostname is cased differently.

    Pass preloaded maps (_inventory_maps) when calling this for a batch of
    devices; omitting them falls back to one query per table, fine for the
    single-row case (ensure_device).
    """
    host = dev.hostname.lower()
    if dev.computer_id is None:
        comp = (
            computers.get(host)
            if computers is not None
            else session.exec(select(Computer).where(func.lower(Computer.hostname) == host)).first()
        )
        if comp:
            dev.computer_id = comp.id
            dev.location = dev.location or comp.location
    if dev.cash_register_id is None:
        cr = (
            registers.get(host)
            if registers is not None
            else session.exec(select(CashRegister).where(func.lower(CashRegister.hostname) == host)).first()
        )
        if cr:
            dev.cash_register_id = cr.id
            dev.location = dev.location or _cr_location(cr)
    if dev.media_player_id is None:
        mp = (
            nettops.get(host)
            if nettops is not None
            else session.exec(
                select(MediaPlayer).where(
                    func.lower(MediaPlayer.hostname) == host, MediaPlayer.device_type == _NETTOP
                )
            ).first()
        )
        if mp:
            dev.media_player_id = mp.id
    # label by the strongest source that actually linked (cash_register > computer > media_player)
    linked_kind = (
        "cash_register" if dev.cash_register_id
        else "computer" if dev.computer_id
        else "media_player" if dev.media_player_id
        else None
    )
    if linked_kind:
        dev.source_kind = linked_kind


def _inventory_rows(session: Session) -> list[tuple[str, str, str | None]]:
    """(hostname, source_kind, location) for every RustDesk-capable inventory endpoint.

    Cash registers and computers are Windows by definition; of the media players
    only nettops are (iconbit/twix run Android).
    """
    rows: list[tuple[str, str, str | None]] = []
    for cr in session.exec(select(CashRegister)).all():
        if cr.hostname and cr.hostname.strip():
            rows.append((cr.hostname.strip(), "cash_register", _cr_location(cr)))
    for host, loc in session.exec(select(Computer.hostname, Computer.location)).all():
        if host and host.strip():
            rows.append((host.strip(), "computer", loc))
    for host, name in session.exec(
        select(MediaPlayer.hostname, MediaPlayer.name).where(MediaPlayer.device_type == _NETTOP)
    ).all():
        if host and host.strip():
            rows.append((host.strip(), "media_player", None))
    return rows


def seed_from_inventory(session: Session) -> int:
    """Mirror the InfraScope endpoint inventory into RemoteAccessDevice rows.

    Sources: every CashRegister, every Computer, and MediaPlayers of type 'nettop'.
    Idempotent - an existing row only gets its inventory links, source_kind and
    (if still blank) location refreshed; its desired config and password are never
    touched here.
    """
    # keyed lower() - same case-insensitivity fix as _get_or_create_device,
    # so this loop doesn't mint a duplicate for a hostname it already has
    # under different casing (e.g. seen from CashRegister once, Computer since)
    existing = {d.hostname.lower(): d for d in session.exec(select(RemoteAccessDevice)).all()}
    computers, registers, nettops = _inventory_maps(session)
    created = 0
    for hostname, kind, location in _inventory_rows(session):
        dev = existing.get(hostname.lower())
        if dev is None:
            dev = RemoteAccessDevice(
                hostname=hostname,
                rustdesk_id=_hostname_to_rid(hostname),
                source_kind=kind,
                location=location,
                permanent_password=default_password(),
            )
            existing[hostname.lower()] = dev
            session.add(dev)
            created += 1
        else:
            if _SOURCE_RANK.get(kind, 0) > _SOURCE_RANK.get(dev.source_kind, 0):
                dev.source_kind = kind
            if not dev.location and location:
                dev.location = location
            if not dev.permanent_password:
                dev.permanent_password = default_password()
        _link_inventory(session, dev, computers=computers, registers=registers, nettops=nettops)
    session.commit()
    return created


def refresh_status_from_inventory(session: Session) -> int:
    """Copy InfraScope's own reachability result onto the device as `host_online`.

    This is a *separate* signal from `online` (which is RustDesk-console truth):
    the host answering a ping tells you nothing about whether the RustDesk client
    is running or connected. The UI shows the two side by side.
    """
    updated = 0
    for dev in session.exec(select(RemoteAccessDevice)).all():
        inv_online, inv_polled = _inventory_status(session, dev)
        if inv_online is None:
            continue
        if dev.host_online != inv_online or dev.host_last_seen_at != inv_polled:
            dev.host_online = inv_online
            dev.host_last_seen_at = inv_polled
            dev.updated_at = _now()
            updated += 1
    if updated:
        session.commit()
    return updated


def _inventory_status(session: Session, dev: RemoteAccessDevice) -> tuple[bool | None, datetime | None]:
    for model, fk in (
        (Computer, dev.computer_id),
        (CashRegister, dev.cash_register_id),
        (MediaPlayer, dev.media_player_id),
    ):
        if fk is None:
            continue
        row = session.get(model, fk)
        if row is not None:
            return row.is_online, row.last_polled_at
    return None, None


def ensure_device(
    session: Session,
    *,
    hostname: str,
    rustdesk_id: str | None = None,
    permanent_password: str | None = None,
) -> RemoteAccessDevice:
    """Create/link a device row and stamp its desired id + password.

    Used by the RustDesk buttons on the device cards. Does not touch any machine -
    the config it records is what the next rollout run will apply.
    """
    dev = _get_or_create_device(session, hostname)
    _link_inventory(session, dev)
    was_rid, was_pw = dev.rustdesk_id, dev.permanent_password
    if rustdesk_id:
        dev.rustdesk_id = rustdesk_id
    elif not dev.rustdesk_id:
        dev.rustdesk_id = _hostname_to_rid(hostname)
    if permanent_password:
        dev.permanent_password = permanent_password
        dev.password_rotated_at = _now()
        dev.ab_password_pushed = False
    elif not dev.permanent_password:
        dev.permanent_password = default_password()
        dev.password_rotated_at = _now()
    # a manual id/password edit on an already-configured device is just as
    # stale as a rotate_password() call - the machine keeps the old values
    # until the next redeploy run
    if dev.rustdesk_id != was_rid or dev.permanent_password != was_pw:
        mark_config_stale(dev)
    dev.managed = True
    dev.updated_at = _now()
    session.add(dev)
    session.commit()
    session.refresh(dev)
    return dev


async def release_inventory_row(
    session: Session,
    *,
    computer_id: uuid.UUID | None = None,
    cash_register_id: uuid.UUID | None = None,
    media_player_id: uuid.UUID | None = None,
) -> int:
    """Let go of the remote-access entries that point at an inventory row about to be deleted.

    RemoteAccessDevice has real foreign keys to computer / cashregister / mediaplayer
    (NO ACTION), so deleting a row that an entry still points at fails in the database.
    Each entry is taken out of management the same way "delete device" does it (managed
    off, shared-book row dropped - so it does not linger in the list for a machine that
    is gone) and then unlinked. Returns how many entries were released.
    """
    conditions = []
    if computer_id is not None:
        conditions.append(RemoteAccessDevice.computer_id == computer_id)
    if cash_register_id is not None:
        conditions.append(RemoteAccessDevice.cash_register_id == cash_register_id)
    if media_player_id is not None:
        conditions.append(RemoteAccessDevice.media_player_id == media_player_id)
    if not conditions:
        return 0
    devices = session.exec(select(RemoteAccessDevice).where(or_(*conditions))).all()
    for dev in devices:
        await delete_device(session, dev)
        if computer_id is not None and dev.computer_id == computer_id:
            dev.computer_id = None
        if cash_register_id is not None and dev.cash_register_id == cash_register_id:
            dev.cash_register_id = None
        if media_player_id is not None and dev.media_player_id == media_player_id:
            dev.media_player_id = None
        session.add(dev)
    if devices:
        session.commit()
    return len(devices)
