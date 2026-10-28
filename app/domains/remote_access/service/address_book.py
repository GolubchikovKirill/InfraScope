"""Shared address book: one console collection holding every managed device with
its password, so connecting is one click and nobody types a secret."""

from __future__ import annotations

import logging
from typing import Any

from sqlmodel import Session, select

from app.core.config import settings
from app.domains.remote_access import rustdesk_client
from app.domains.remote_access.models import RemoteAccessConsoleAccount, RemoteAccessDevice

from .accounts import ensure_shared_book
from .devices import _hostname_to_rid, _now, default_password, hostname_type_tag

logger = logging.getLogger("app.domains.remote_access.service")


def _ab_payload(dev: RemoteAccessDevice, *, collection_id: int, owner_id: int) -> dict:
    tags = [dev.source_kind]
    if dev.location:
        tags.append(dev.location)
    type_tag = hostname_type_tag(dev.hostname)
    if type_tag and type_tag not in tags:
        tags.append(type_tag)
    return {
        "id": dev.rustdesk_id or _hostname_to_rid(dev.hostname),
        "alias": dev.hostname,
        "hostname": dev.hostname,
        "platform": "Windows",
        "tags": tags,
        # a shared-book row stores the peer password in `password` (the personal
        # book uses `hash`) - this is what makes connecting one click
        "password": dev.permanent_password or default_password(),
        "user_id": owner_id,
        "collection_id": collection_id,
    }


async def push_shared_address_book(
    session: Session, devices: list[RemoteAccessDevice]
) -> dict[str, int]:
    """Upsert managed devices into the shared console address book.

    Existing rows are updated in place (matched by the console's `row_id`, which
    we cache) so tags and passwords stay current instead of piling up duplicates.
    """
    targets = [d for d in devices if d.managed and d.rustdesk_id]
    if not targets:
        return {"pushed": 0, "created": 0, "updated": 0, "failed": 0}

    collection_id, owner_id = await ensure_shared_book()
    existing = {
        str(r.get("id") or ""): r
        for r in await rustdesk_client.list_address_book_rows(
            user_id=owner_id, collection_id=collection_id
        )
    }

    now = _now()
    created = updated = failed = 0
    for dev in targets:
        payload = _ab_payload(dev, collection_id=collection_id, owner_id=owner_id)
        current = existing.get(payload["id"])
        row_id = int(current["row_id"]) if current and current.get("row_id") else dev.ab_row_id
        try:
            if row_id:
                await rustdesk_client.update_address_book_row({**payload, "row_id": row_id})
                updated += 1
            else:
                await rustdesk_client.create_address_book_row(payload)
                created += 1
        except Exception as exc:
            logger.warning("address-book push failed for %s: %s", dev.hostname, exc)
            failed += 1
            continue
        dev.ab_row_id = row_id or dev.ab_row_id
        dev.in_address_book = True
        dev.ab_password_pushed = True
        dev.updated_at = now
        session.add(dev)
    session.commit()

    # a row created just now has no row_id yet; pick it up so the next push updates
    if created:
        fresh = {
            str(r.get("id") or ""): r
            for r in await rustdesk_client.list_address_book_rows(
                user_id=owner_id, collection_id=collection_id
            )
        }
        for dev in targets:
            row = fresh.get(dev.rustdesk_id or "")
            if row and row.get("row_id") and not dev.ab_row_id:
                dev.ab_row_id = int(row["row_id"])
                session.add(dev)
        session.commit()

    return {"pushed": created + updated, "created": created, "updated": updated, "failed": failed}


async def sync_address_book(session: Session) -> dict[str, int]:
    devices = list(
        session.exec(select(RemoteAccessDevice).where(RemoteAccessDevice.managed == True))  # noqa: E712
    )
    return await push_shared_address_book(session, devices)


async def sync_stale_address_book(session: Session) -> dict[str, int]:
    """Push whichever managed devices the shared book doesn't actually have.

    The local flags (in_address_book, ab_password_pushed) alone used to
    decide this - fine as long as nothing removes a row from the console
    without going through here, but delete_device (or anything else that
    calls delete_address_book_row) can, and then nothing ever rechecked
    against the console again. Caught live: a batch of duplicate-hostname
    cleanups quietly dropped 28 real devices out of the shared book, and
    InfraScope kept every one of their flags saying "present" - the console
    and the address_book_status page told two different stories until this
    ran. So this also asks the console directly, once, and treats a device
    whose rustdesk_id isn't in that answer as needing a push regardless of
    what its flags say - and clears its (now-dangling) ab_row_id first, so
    push_shared_address_book creates a fresh row instead of failing an
    update against a row_id the console has already forgotten.
    """
    collection_id, owner_id = await ensure_shared_book()
    live_ids = {
        str(r.get("id") or "")
        for r in await rustdesk_client.list_address_book_rows(user_id=owner_id, collection_id=collection_id)
    }

    devices = []
    for dev in session.exec(select(RemoteAccessDevice).where(RemoteAccessDevice.managed == True)):  # noqa: E712
        missing_from_console = bool(dev.rustdesk_id) and dev.rustdesk_id not in live_ids
        if missing_from_console:
            dev.ab_row_id = None
            dev.in_address_book = False
            dev.ab_password_pushed = False
        if not dev.in_address_book or not dev.ab_password_pushed:
            devices.append(dev)
    if not devices:
        return {"pushed": 0, "created": 0, "updated": 0, "failed": 0}
    return await push_shared_address_book(session, devices)


async def address_book_status(session: Session) -> dict[str, Any]:
    """What the page shows above the device grid: which book, how big, who sees it.

    `missing` is the reconciliation sync_stale_address_book also does - devices
    InfraScope believes are in the book (in_address_book=True) but whose
    rustdesk_id the console doesn't actually have right now. Normally 0; the
    next beat tick (every 2 min) re-pushes and clears it on its own, so a
    nonzero reading here is either "wait a couple minutes" or, if it's stuck
    positive across ticks, worth a look.
    """
    collection_id, owner_id = await ensure_shared_book()
    rows = await rustdesk_client.list_address_book_rows(
        user_id=owner_id, collection_id=collection_id
    )
    live_ids = {str(r.get("id") or "") for r in rows}
    believed_present = session.exec(
        select(RemoteAccessDevice).where(
            RemoteAccessDevice.managed == True,  # noqa: E712
            RemoteAccessDevice.in_address_book == True,  # noqa: E712
        )
    ).all()
    missing = sum(1 for d in believed_present if d.rustdesk_id and d.rustdesk_id not in live_ids)
    accounts = session.exec(
        select(RemoteAccessConsoleAccount).where(RemoteAccessConsoleAccount.active == True)  # noqa: E712
    ).all()
    return {
        "name": settings.RUSTDESK_SHARED_BOOK_NAME,
        "collection_id": collection_id,
        "missing": missing,
        "owner_user_id": owner_id,
        "entries": len(rows),
        "shared_with_group": settings.RUSTDESK_ADMIN_GROUP_NAME,
        "accounts": len(accounts),
    }
