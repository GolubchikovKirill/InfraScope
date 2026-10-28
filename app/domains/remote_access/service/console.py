"""Reconciliation with what the RustDesk console actually sees: peers online,
clients that reported a canonical id, machines that are not in the list yet."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlmodel import Session, select

from app.core.config import settings
from app.domains.remote_access import rustdesk_client
from app.domains.remote_access.models import RemoteAccessDevice

from .devices import (
    _find_device,
    _get_or_create_device,
    _hostname_to_rid,
    _now,
    apply_deploy_profile,
    suggested_profile,
)
from .inventory import _inventory_maps, _link_inventory, ensure_device


def _peer_online(peer: dict[str, Any], now: datetime) -> bool:
    """The admin peer list has no boolean - derive it from `last_online_time`."""
    last = peer.get("last_online_time", 0)
    try:
        last_ts = int(last)
    except (TypeError, ValueError):
        return False
    if last_ts <= 0:
        return False
    return (now.timestamp() - last_ts) <= settings.RUSTDESK_DEVICE_STALE_SECONDS


def _peer_last_online(peer: dict[str, Any]) -> int:
    """`last_online_time` as an int, 0 when missing/unparseable - lets us pick the
    freshest of several console peers that all map to one device."""
    try:
        return max(int(peer.get("last_online_time", 0)), 0)
    except (TypeError, ValueError):
        return 0


# how long a "failed" report must have stood before a healthy canonical client cancels it
FAILED_HEAL_AFTER = timedelta(hours=1)


def _failure_outlived(dev: RemoteAccessDevice, now: datetime) -> bool:
    if dev.deploy_state != "failed":
        return False
    reported = dev.deploy_reported_at
    if reported is None:
        return True
    if reported.tzinfo is None:
        reported = reported.replace(tzinfo=UTC)
    return now - reported > FAILED_HEAL_AFTER


async def sync_from_console(session: Session) -> dict[str, int]:
    """Fold live RustDesk-console status into RemoteAccessDevice rows.

    The admin peer list (`/api/admin/peer/list`) is the richer source: it carries
    the installed client `version`, `os`, `hostname` and `last_online_time`,
    none of which the client API's `/api/peers` returns. The shared address book
    is not consulted for status - it caches an `online` flag that goes stale.

    Only updates devices InfraScope already tracks - never creates one. The
    console's peer list is *everything* that has ever connected, including an
    engineer's own laptop logged in to drive the shared book, not just the
    fleet endpoints seed_from_inventory put here on purpose. Used to call
    _get_or_create_device unconditionally: caught live minting a tracked,
    managed=True "macbook-pro" row - with a password generated and pushed to
    the shared book - the moment someone's personal machine connected over
    VPN and logged into the console. seed_from_inventory (backed by real
    inventory: Computer/CashRegister/MediaPlayer) is the only thing that
    should decide what gets managed.
    """
    now = _now()
    status: dict[str, bool] = {}
    peers = await rustdesk_client.list_admin_peers()
    computers, registers, nettops = _inventory_maps(session)

    # Group every console peer by the device it belongs to. One device can carry
    # several peers: the canonical one (id == hostname-derived rid, i.e. running
    # our config) plus stale factory-numeric-id registrations left over from a
    # deploy that first connected before the custom id was written. Taking the
    # last peer in the list blindly used to latch a numeric id - and then
    # sync_stale_address_book, seeing that id absent from the shared book,
    # recreated an address-book row for it on every tick, forever.
    by_host: dict[str, list[dict[str, Any]]] = {}
    seen = 0
    for peer in peers:
        rid = str(peer.get("id") or "").strip()
        hostname = (peer.get("hostname") or "").strip()
        if not rid and not hostname:
            continue
        seen += 1
        dev = _find_device(session, hostname or rid)
        if dev is None:
            continue
        by_host.setdefault(dev.hostname.lower(), []).append(peer)

    healthy_canonical: set[str] = set()
    for dev in session.exec(select(RemoteAccessDevice)):
        group = by_host.get(dev.hostname.lower())
        if not group:
            continue
        _link_inventory(session, dev, computers=computers, registers=registers, nettops=nettops)
        canonical = _hostname_to_rid(dev.hostname)
        # the peer running our config wins; failing that, the freshest one
        preferred = next(
            (p for p in group if str(p.get("id") or "").strip().lower() == canonical.lower()),
            max(group, key=_peer_last_online),
        )
        rid = str(preferred.get("id") or "").strip()
        if rid:
            dev.rustdesk_id = rid
            status[rid] = _peer_online(preferred, now)
            if rid.lower() == canonical.lower() and status[rid]:
                healthy_canonical.add(dev.hostname.lower())
        dev.installed_version = (preferred.get("version") or None) or dev.installed_version
        dev.logged_in_user = (preferred.get("username") or None) or dev.logged_in_user
        dev.last_ip = (preferred.get("last_online_ip") or None) or dev.last_ip
        dev.updated_at = now

    # one pass over every tracked device: online == exactly what the console says,
    # None for anything the console has never registered (no client yet)
    for dev in session.exec(select(RemoteAccessDevice)):
        want = status.get(dev.rustdesk_id or "")  # True / False / None
        changed = dev.online != want
        if want:
            dev.last_seen_at = now
        elif want is None and dev.last_seen_at is not None:
            dev.last_seen_at = None
            changed = True
        if changed:
            dev.online = want
            dev.updated_at = now
        # The push/offline rollout sends no deploy/report, so "stale" (set on a
        # password rotation) and "pending" (deploy requested) had no path back
        # to "configured" - the chip stayed a false warning forever even with
        # the client demonstrably online under our id. Clear it from the
        # console's own signal instead: the client is online under its
        # canonical hostname-derived id (so our config ran and stuck), and for
        # "stale" the rotated password is already pushed to the shared book.
        if dev.hostname.lower() in healthy_canonical and (
            dev.deploy_state == "pending"
            or (dev.deploy_state == "stale" and dev.ab_password_pushed)
        ):
            dev.deploy_state = "configured"
            dev.deploy_reported_at = now
            dev.updated_at = now
        elif dev.hostname.lower() in healthy_canonical and _failure_outlived(dev, now):
            # A "failed" report is a snapshot from the moment of that run. A client that has
            # been online under its own canonical id for longer than FAILED_HEAL_AFTER since
            # then is demonstrably working (caught live: VNA-SKD-14 said "ошибка развертывания"
            # for 16 days while an engineer connected to it daily). A *fresh* failure stays.
            old = (dev.deploy_detail or "").strip()
            dev.deploy_state = "configured"
            dev.deploy_detail = (
                f"Ошибка снята автоматически: клиент онлайн под ID {dev.rustdesk_id}."
                + (f" Было: {old}" if old else "")
            )[:512]
            dev.deploy_reported_at = now
            dev.updated_at = now
    session.commit()
    return {"peers_seen": seen}


async def list_unlisted_console_peers(session: Session) -> dict[str, Any]:
    """Console machines InfraScope does not track.

    sync_from_console deliberately never creates a device: the console lists
    *everything that ever connected* (it once minted a managed row, with a
    generated password, for someone's personal MacBook), and inventory decides
    what is managed. The catch is that machines outside the inventory - the IT
    department's own workstations - then never show up at all, however healthy
    their RustDesk client is. This is the missing half: show them, and let a
    person decide (adopt_peer / dismiss_peer). Nothing here writes.

    A hostname already present as a row is skipped whether it is managed or was
    removed on purpose (managed=False): removing a device is a decision, and it
    must not come back as a suggestion.
    """
    now = _now()
    peers = await rustdesk_client.list_admin_peers()
    known = {h.lower() for h in session.exec(select(RemoteAccessDevice.hostname)).all() if h}
    best: dict[str, dict[str, Any]] = {}
    nameless = 0
    for peer in peers:
        hostname = (peer.get("hostname") or "").strip()
        if not hostname:
            nameless += 1
            continue
        key = hostname.lower()
        if key in known:
            continue
        if key not in best or _peer_last_online(peer) > _peer_last_online(best[key]):
            best[key] = peer

    items = []
    for peer in best.values():
        hostname = (peer.get("hostname") or "").strip()
        last = _peer_last_online(peer)
        items.append(
            {
                "hostname": hostname,
                "rustdesk_id": (str(peer.get("id") or "").strip() or None),
                "os": (peer.get("os") or None),
                "version": (peer.get("version") or None),
                "username": (peer.get("username") or None),
                "online": _peer_online(peer, now),
                "last_online": datetime.fromtimestamp(last, tz=UTC) if last else None,
                "suggested_profile": suggested_profile(hostname),
            }
        )
    items.sort(key=lambda i: (not i["online"], i["hostname"].lower()))
    return {"data": items, "count": len(items), "nameless_peers": nameless}


def adopt_peer(session: Session, *, hostname: str, profile: str | None = None) -> RemoteAccessDevice:
    """Start managing a console machine: same as the "add device" button, plus
    the deploy profile in one step. Records config only - the machine itself is
    untouched until a rollout runs on it."""
    dev = ensure_device(session, hostname=hostname)
    return apply_deploy_profile(session, dev, profile or suggested_profile(hostname))


def dismiss_peer(session: Session, *, hostname: str) -> RemoteAccessDevice:
    """Hide a console machine from the "not in the list" suggestions for good.

    Stored as a managed=False row - the existing meaning of "removed on purpose"
    (delete_device) - so no password is ever pushed and no address-book entry is
    made for it (both filter on managed), and the console sync never turns it
    back on. Adopting it later is still possible through ensure_device.
    """
    dev = _get_or_create_device(session, hostname)
    dev.managed = False
    session.add(dev)
    session.commit()
    session.refresh(dev)
    return dev
