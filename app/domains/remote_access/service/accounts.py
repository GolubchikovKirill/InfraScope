"""Console accounts: each engineer gets a RustDesk login in the console group the
shared address book is shared with, so all of them see the whole fleet."""

from __future__ import annotations

import uuid
from typing import Any

from sqlmodel import Session, select

from app.core.config import settings
from app.domains.remote_access import rustdesk_client
from app.domains.remote_access.models import RemoteAccessConsoleAccount

from .devices import _now, generate_password


async def ensure_console_group() -> int:
    """The console group every InfraScope-managed engineer account joins."""
    name = settings.RUSTDESK_ADMIN_GROUP_NAME.strip()
    for group in await rustdesk_client.list_groups():
        if str(group.get("name") or "").strip() == name:
            return int(group["id"])
    await rustdesk_client.create_group(name, rustdesk_client.GROUP_TYPE_SHARED)
    for group in await rustdesk_client.list_groups():
        if str(group.get("name") or "").strip() == name:
            return int(group["id"])
    raise RuntimeError(f"console group {name!r} was created but does not list")


async def ensure_shared_book() -> tuple[int, int]:
    """Ensure the shared address book exists and the engineer group can read it.

    Returns (collection_id, owner_user_id). The collection is owned by whichever
    console account our token belongs to; everyone else reaches it through the
    group share rule, so adding an engineer needs no address-book work at all.
    """
    owner_id = await rustdesk_client.current_console_user_id()
    if not owner_id:
        raise RuntimeError("console did not identify the account behind the API token")

    name = settings.RUSTDESK_SHARED_BOOK_NAME.strip()
    collection_id = 0
    for col in await rustdesk_client.list_collections():
        if str(col.get("name") or "").strip() == name:
            collection_id = int(col["id"])
            break
    if not collection_id:
        await rustdesk_client.create_collection(name, owner_id)
        for col in await rustdesk_client.list_collections():
            if str(col.get("name") or "").strip() == name:
                collection_id = int(col["id"])
                break
    if not collection_id:
        raise RuntimeError(f"shared address book {name!r} was created but does not list")

    group_id = await ensure_console_group()
    rules = await rustdesk_client.list_collection_rules(collection_id)
    shared = any(
        int(r.get("type") or 0) == rustdesk_client.RULE_TYPE_GROUP
        and int(r.get("to_id") or 0) == group_id
        for r in rules
    )
    if not shared:
        await rustdesk_client.create_collection_rule(
            collection_id=collection_id,
            owner_id=owner_id,
            to_id=group_id,
            rule_type=rustdesk_client.RULE_TYPE_GROUP,
            rule=rustdesk_client.RULE_READ,
        )
    return collection_id, owner_id


async def provision_account(
    session: Session,
    *,
    username: str,
    display_name: str | None = None,
    email: str | None = None,
    is_admin: bool = False,
    password: str | None = None,
    infrascope_user_id: uuid.UUID | None = None,
) -> tuple[RemoteAccessConsoleAccount, str]:
    """Create a console login for an engineer and hand back its password once.

    The password is never persisted here - the caller shows it and it is gone.
    """
    username = username.strip()
    group_id = await ensure_console_group()
    secret = (password or "").strip() or generate_password(16)

    # The console stores logins lower-cased ("KlimovMA" is kept as "klimovma"), so a
    # case-sensitive lookup misses an account it already has and the create then
    # fails on the UNIQUE constraint - which is also how a retry after a half-done
    # first attempt (account made, password step failed) used to get stuck.
    async def _console_by_login() -> dict[str, dict[str, Any]]:
        return {
            str(u.get("username") or "").strip().casefold(): u
            for u in await rustdesk_client.list_console_users()
        }

    existing_console = await _console_by_login()
    if username.casefold() not in existing_console:
        await rustdesk_client.create_console_user(
            username=username,
            group_id=group_id,
            is_admin=is_admin,
            email=(email or "").strip(),
            nickname=(display_name or "").strip(),
        )
        existing_console = await _console_by_login()
    console_user = existing_console.get(username.casefold())
    if not console_user:
        raise RuntimeError(f"console account {username!r} was created but does not list")
    console_user_id = int(console_user["id"])
    username = str(console_user.get("username") or username).strip()
    await rustdesk_client.set_console_user_password(console_user_id, secret)

    # already in the group -> already sees the shared book
    await ensure_shared_book()

    row = session.exec(
        select(RemoteAccessConsoleAccount).where(RemoteAccessConsoleAccount.username == username)
    ).first()
    if row is None:
        row = RemoteAccessConsoleAccount(username=username)
        session.add(row)
    row.console_user_id = console_user_id
    row.display_name = (display_name or "").strip() or None
    row.email = (email or "").strip() or None
    row.is_admin = is_admin
    row.infrascope_user_id = infrascope_user_id
    row.active = True
    row.book_shared = True
    row.last_synced_at = _now()
    row.updated_at = _now()
    session.commit()
    session.refresh(row)
    return row, secret


async def reset_account_password(
    session: Session, account: RemoteAccessConsoleAccount, password: str | None = None
) -> str:
    if not account.console_user_id:
        raise RuntimeError("account has no console user id - run an account sync first")
    secret = (password or "").strip() or generate_password(16)
    await rustdesk_client.set_console_user_password(account.console_user_id, secret)
    account.updated_at = _now()
    session.add(account)
    session.commit()
    return secret


async def set_account_active(
    session: Session, account: RemoteAccessConsoleAccount, active: bool
) -> RemoteAccessConsoleAccount:
    """Enable/disable the console login.

    Disabling rather than deleting: the console refuses to delete its last admin
    and its delete payload is undocumented, while `status` is a plain toggle.
    """
    if not account.console_user_id:
        raise RuntimeError("account has no console user id - run an account sync first")
    group_id = await ensure_console_group()
    await rustdesk_client.update_console_user(
        user_id=account.console_user_id,
        username=account.username,
        group_id=group_id,
        is_admin=account.is_admin,
        status=rustdesk_client.STATUS_ENABLED if active else rustdesk_client.STATUS_DISABLED,
        email=account.email or "",
        nickname=account.display_name or "",
    )
    account.active = active
    account.updated_at = _now()
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


async def sync_accounts(session: Session) -> dict[str, int]:
    """Pull the console's user list into our account rows.

    Accounts created directly in the console show up here too, so the page is a
    true picture of who can connect - not just of what InfraScope created.
    """
    rows = {
        r.username: r
        for r in session.exec(select(RemoteAccessConsoleAccount)).all()
    }
    now = _now()
    seen = 0
    for user in await rustdesk_client.list_console_users():
        username = str(user.get("username") or "").strip()
        if not username:
            continue
        seen += 1
        row = rows.get(username)
        if row is None:
            row = RemoteAccessConsoleAccount(username=username)
            session.add(row)
            rows[username] = row
        row.console_user_id = int(user.get("id") or 0) or None
        row.is_admin = bool(user.get("is_admin"))
        row.email = (user.get("email") or None) or row.email
        row.display_name = (user.get("nickname") or None) or row.display_name
        row.active = int(user.get("status") or rustdesk_client.STATUS_ENABLED) == rustdesk_client.STATUS_ENABLED
        row.last_synced_at = now
        row.updated_at = now
    session.commit()
    return {"accounts_seen": seen}
