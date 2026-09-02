"""Reconciliation between the RustDesk console, InfraScope inventory and the address book.

InfraScope tracks and administers the self-hosted RustDesk fleet; it does not push
the client. The preconfigured client package is rolled out through Kaspersky
Security Center (see docs/rustdesk-ksc-deployment.md). This module keeps the
device rows in sync with inventory + the console, and owns the address-book push.
"""

from __future__ import annotations

import logging
import secrets
import string
import uuid
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from app.core.config import settings
from app.domains.inventory.models import Computer, MediaPlayer
from app.domains.operations.models import CashRegister
from app.domains.remote_access import rustdesk_client
from app.domains.remote_access.models import RemoteAccessDevice

logger = logging.getLogger(__name__)

# only nettop media players are Windows boxes; iconbit/twix are Android sticks
_NETTOP = "nettop"
# a host can sit in two inventory tables (a till also tracked as a computer);
# the higher-ranked source owns its source_kind label
_SOURCE_RANK = {"cash_register": 3, "computer": 2, "media_player": 1}

_PW_ALPHABET = string.ascii_letters + string.digits  # no symbols: avoids shell/TOML quoting traps


def generate_password(length: int = 20) -> str:
    return "".join(secrets.choice(_PW_ALPHABET) for _ in range(length))


def _now() -> datetime:
    return datetime.now(UTC)


def _hostname_to_rid(hostname: str) -> str:
    # RustDesk custom IDs allow only [A-Za-z0-9_]
    rid = "".join(c if c.isalnum() else "_" for c in hostname)
    return rid[:32]


# --------------------------------------------------------------------------- #
# device inventory sync                                                       #
# --------------------------------------------------------------------------- #
def _get_or_create_device(session: Session, hostname: str) -> RemoteAccessDevice:
    host = hostname.strip()
    dev = session.exec(select(RemoteAccessDevice).where(RemoteAccessDevice.hostname == host)).first()
    if dev:
        return dev
    dev = RemoteAccessDevice(hostname=host, rustdesk_id=_hostname_to_rid(host))
    session.add(dev)
    session.flush()
    return dev


def _cr_location(cr: CashRegister) -> str | None:
    return cr.store_number or cr.store_code or None


def _link_inventory(session: Session, dev: RemoteAccessDevice) -> None:
    """(Re)bind a device row to every inventory row that shares its hostname."""
    host = dev.hostname
    if dev.computer_id is None:
        comp = session.exec(select(Computer).where(Computer.hostname == host)).first()
        if comp:
            dev.computer_id = comp.id
            dev.location = dev.location or comp.location
    if dev.cash_register_id is None:
        cr = session.exec(select(CashRegister).where(CashRegister.hostname == host)).first()
        if cr:
            dev.cash_register_id = cr.id
            dev.location = dev.location or _cr_location(cr)
    if dev.media_player_id is None:
        mp = session.exec(
            select(MediaPlayer).where(
                MediaPlayer.hostname == host, MediaPlayer.device_type == _NETTOP
            )
        ).first()
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
    existing = {d.hostname: d for d in session.exec(select(RemoteAccessDevice)).all()}
    created = 0
    for hostname, kind, location in _inventory_rows(session):
        dev = existing.get(hostname)
        if dev is None:
            dev = RemoteAccessDevice(
                hostname=hostname,
                rustdesk_id=_hostname_to_rid(hostname),
                source_kind=kind,
                location=location,
            )
            existing[hostname] = dev
            session.add(dev)
            created += 1
        else:
            if _SOURCE_RANK.get(kind, 0) > _SOURCE_RANK.get(dev.source_kind, 0):
                dev.source_kind = kind
            if not dev.location and location:
                dev.location = location
        _link_inventory(session, dev)
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


async def sync_from_console(session: Session) -> dict[str, int]:
    """Pull the console peer list and fold live status into RemoteAccessDevice rows."""
    peers = await rustdesk_client.list_peers()
    stale_after = timedelta(seconds=settings.RUSTDESK_DEVICE_STALE_SECONDS)
    seen = 0
    for p in peers:
        hostname = (p.get("hostname") or p.get("host") or "").strip()
        if not hostname:
            continue
        seen += 1
        dev = _get_or_create_device(session, hostname)
        _link_inventory(session, dev)
        rid = str(p.get("id") or "").strip() or None
        if rid:
            dev.rustdesk_id = rid
        ver = str(p.get("version") or "").strip() or None
        if ver:
            dev.installed_version = ver
        dev.logged_in_user = (p.get("username") or p.get("user") or None) or dev.logged_in_user
        dev.last_ip = (p.get("last_online_ip") or p.get("ip") or None) or dev.last_ip
        ts = p.get("last_online_time") or p.get("last_online")
        if isinstance(ts, (int, float)) and ts > 0:
            dev.last_seen_at = datetime.fromtimestamp(ts, tz=UTC)
        elif isinstance(ts, str) and ts:
            try:
                dev.last_seen_at = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                pass
        dev.online = bool(dev.last_seen_at and (_now() - dev.last_seen_at) < stale_after)
        dev.updated_at = _now()
    session.commit()
    return {"peers_seen": seen}


# --------------------------------------------------------------------------- #
# desired config                                                              #
# --------------------------------------------------------------------------- #
def ensure_device(
    session: Session,
    *,
    hostname: str,
    rustdesk_id: str | None = None,
    permanent_password: str | None = None,
) -> RemoteAccessDevice:
    """Create/link a device row and stamp its desired id + password.

    Used by the RustDesk buttons on the device cards. Does not touch any machine -
    the config it records is what the KSC package should carry.
    """
    dev = _get_or_create_device(session, hostname)
    _link_inventory(session, dev)
    if rustdesk_id:
        dev.rustdesk_id = rustdesk_id
    elif not dev.rustdesk_id:
        dev.rustdesk_id = _hostname_to_rid(hostname)
    if permanent_password:
        dev.permanent_password = permanent_password
        dev.password_rotated_at = _now()
    elif not dev.permanent_password:
        dev.permanent_password = generate_password()
        dev.password_rotated_at = _now()
    dev.managed = True
    dev.updated_at = _now()
    session.add(dev)
    session.commit()
    session.refresh(dev)
    return dev


def rotate_password(session: Session, dev: RemoteAccessDevice) -> RemoteAccessDevice:
    """Generate a fresh password. The operator must re-push the KSC package to
    actually apply it on the machine."""
    dev.permanent_password = generate_password()
    dev.password_rotated_at = _now()
    dev.updated_at = _now()
    session.add(dev)
    session.commit()
    session.refresh(dev)
    return dev


def package_config(dev: RemoteAccessDevice) -> dict:
    """Everything the KSC post-install step needs for this machine.

    `configure.ps1` in rustdesk-ksc/ consumes exactly these keys.
    """
    return {
        "hostname": dev.hostname,
        "rustdesk_id": dev.rustdesk_id or _hostname_to_rid(dev.hostname),
        "id_server": settings.RUSTDESK_ID_SERVER,
        "relay_server": settings.RUSTDESK_RELAY_SERVER,
        "api_server": settings.RUSTDESK_API_URL,
        "key": settings.RUSTDESK_KEY,
        "permanent_password": dev.permanent_password,
        "installer_version": settings.RUSTDESK_INSTALLER_VERSION,
        "hidden": dev.desired_hidden,
        "block_outgoing": dev.desired_block_outgoing,
        "unattended": dev.desired_unattended,
    }


# --------------------------------------------------------------------------- #
# address book (console passthrough, InfraScope-owned)                        #
# --------------------------------------------------------------------------- #
def _ab_entry(dev: RemoteAccessDevice) -> dict:
    tags = [dev.source_kind]
    if dev.location:
        tags.append(dev.location)
    return {
        "id": dev.rustdesk_id or _hostname_to_rid(dev.hostname),
        "alias": dev.hostname,
        "tags": tags,
    }


async def push_address_book(session: Session, devices: list[RemoteAccessDevice]) -> dict[str, int]:
    """Upsert the given managed devices into the console's address book."""
    pushed = failed = 0
    for dev in devices:
        if not dev.managed or not dev.rustdesk_id:
            continue
        try:
            await rustdesk_client.upsert_address_book_entry(_ab_entry(dev))
            dev.in_address_book = True
            dev.updated_at = _now()
            session.add(dev)
            pushed += 1
        except Exception as exc:  # noqa: BLE001 - one bad entry shouldn't abort the batch
            logger.warning("address-book push failed for %s: %s", dev.hostname, exc)
            failed += 1
    session.commit()
    return {"pushed": pushed, "failed": failed}


async def sync_address_book(session: Session) -> dict[str, int]:
    devices = list(
        session.exec(select(RemoteAccessDevice).where(RemoteAccessDevice.managed == True))  # noqa: E712
    )
    return await push_address_book(session, devices)


def resolve_scope(
    session: Session,
    *,
    device_ids: list[uuid.UUID] | None,
    location: str | None,
    all_managed: bool,
    source_kind: str | None = None,
) -> list[RemoteAccessDevice]:
    stmt = select(RemoteAccessDevice)
    if device_ids:
        stmt = stmt.where(RemoteAccessDevice.id.in_(device_ids))  # type: ignore[attr-defined]
    elif location or source_kind or all_managed:
        stmt = stmt.where(RemoteAccessDevice.managed == True)  # noqa: E712
        if location:
            stmt = stmt.where(RemoteAccessDevice.location == location)
        if source_kind:
            stmt = stmt.where(RemoteAccessDevice.source_kind == source_kind)
    else:
        return []
    return list(session.exec(stmt).all())
