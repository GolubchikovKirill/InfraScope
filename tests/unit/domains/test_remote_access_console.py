"""Shared address book and console-account provisioning, against a fake console.

These are the two paths that make several engineers usable at once: one shared
book carrying every device *with its password*, shared once with a console group
that every provisioned account joins. Both must be idempotent - the worker runs
them every two minutes.
"""

from __future__ import annotations

import asyncio

from sqlmodel import select

from app.core.config import settings
from app.domains.inventory.models import Computer
from app.domains.remote_access import service
from app.domains.remote_access.models import RemoteAccessConsoleAccount, RemoteAccessDevice


def _dev(db_session, hostname: str) -> RemoteAccessDevice:
    return db_session.exec(
        select(RemoteAccessDevice).where(RemoteAccessDevice.hostname == hostname)
    ).first()


class FakeConsole:
    """A console just real enough to exercise the upsert and provisioning paths."""

    def __init__(self) -> None:
        self.groups: list[dict] = []
        self.collections: list[dict] = []
        self.rules: list[dict] = []
        self.ab_rows: list[dict] = []
        # seeded with the service account our token belongs to, matching the
        # real console: it always has at least one user (the one we log in
        # as), and /user/current carries no id - only /user/list rows do
        self.users: list[dict] = [
            {
                "id": 1,
                "username": "infrascope",
                "group_id": 1,
                "is_admin": True,
                "email": "",
                "nickname": "InfraScope service account",
                "status": service.rustdesk_client.STATUS_ENABLED,
            }
        ]
        self.passwords: dict[int, str] = {}
        self.creates = 0
        self.updates = 0

    def install(self, monkeypatch) -> None:
        rc = service.rustdesk_client
        console = self

        async def current_console_user():
            # matches the real console's shape - no numeric id here, only on
            # /user/list rows (verified live, see rustdesk_client.py)
            return {"username": "infrascope"}

        async def list_groups():
            return list(console.groups)

        async def create_group(name, group_type=rc.GROUP_TYPE_SHARED):
            console.groups.append({"id": len(console.groups) + 10, "name": name, "type": group_type})

        async def list_collections():
            return list(console.collections)

        async def create_collection(name, user_id):
            console.collections.append(
                {"id": len(console.collections) + 100, "name": name, "user_id": user_id}
            )

        async def list_collection_rules(collection_id):
            return [r for r in console.rules if r["collection_id"] == collection_id]

        async def create_collection_rule(
            *, collection_id, owner_id, to_id, rule_type=rc.RULE_TYPE_GROUP, rule=rc.RULE_READ
        ):
            console.rules.append(
                {
                    "user_id": owner_id,
                    "collection_id": collection_id,
                    "to_id": to_id,
                    "type": rule_type,
                    "rule": rule,
                }
            )

        async def list_address_book_rows(*, user_id, collection_id):
            return [
                r
                for r in console.ab_rows
                if r["user_id"] == user_id and r["collection_id"] == collection_id
            ]

        async def create_address_book_row(payload):
            console.creates += 1
            console.ab_rows.append({**payload, "row_id": len(console.ab_rows) + 500})

        async def update_address_book_row(payload):
            console.updates += 1
            for i, r in enumerate(console.ab_rows):
                if r.get("row_id") == payload.get("row_id"):
                    console.ab_rows[i] = {**r, **payload}

        async def list_console_users():
            return list(console.users)

        async def create_console_user(*, username, group_id, is_admin=False, email="", nickname=""):
            console.users.append(
                {
                    "id": len(console.users) + 1,
                    "username": username,
                    "group_id": group_id,
                    "is_admin": is_admin,
                    "email": email,
                    "nickname": nickname,
                    "status": rc.STATUS_ENABLED,
                }
            )

        async def set_console_user_password(user_id, password):
            console.passwords[user_id] = password

        for name in (
            "current_console_user",
            "list_groups",
            "create_group",
            "list_collections",
            "create_collection",
            "list_collection_rules",
            "create_collection_rule",
            "list_address_book_rows",
            "create_address_book_row",
            "update_address_book_row",
            "list_console_users",
            "create_console_user",
            "set_console_user_password",
        ):
            monkeypatch.setattr(rc, name, locals()[name])


def test_push_shared_address_book_creates_then_updates(db_session, monkeypatch) -> None:
    console = FakeConsole()
    console.install(monkeypatch)

    db_session.add(Computer(hostname="VNA-MGR-401", location="A4"))
    db_session.commit()
    service.seed_from_inventory(db_session)
    dev = _dev(db_session, "VNA-MGR-401")
    dev.permanent_password = "kentdful"
    db_session.add(dev)
    db_session.commit()

    res = asyncio.run(service.sync_address_book(db_session))
    assert res["created"] == 1 and res["updated"] == 0
    row = console.ab_rows[0]
    # the password rides along, which is what makes connecting one click
    assert row["id"] == "VNA_MGR_401" and row["password"] == "kentdful"

    dev = _dev(db_session, "VNA-MGR-401")
    assert dev.in_address_book is True and dev.ab_password_pushed is True
    assert dev.ab_row_id is not None  # picked up so the next push updates in place

    # a second push must not duplicate the entry
    res = asyncio.run(service.sync_address_book(db_session))
    assert res["created"] == 0 and res["updated"] == 1
    assert len(console.ab_rows) == 1


def test_shared_book_is_shared_once_with_the_engineer_group(db_session, monkeypatch) -> None:
    console = FakeConsole()
    console.install(monkeypatch)
    db_session.add(Computer(hostname="VNA-MGR-402", location="A4"))
    db_session.commit()
    service.seed_from_inventory(db_session)

    asyncio.run(service.sync_address_book(db_session))

    # one collection, shared with the group rather than per user - so a new
    # engineer inherits the whole fleet just by being in the group
    assert len(console.collections) == 1
    assert console.collections[0]["name"] == settings.RUSTDESK_SHARED_BOOK_NAME
    assert len(console.rules) == 1
    rule = console.rules[0]
    assert rule["type"] == service.rustdesk_client.RULE_TYPE_GROUP
    assert rule["to_id"] == console.groups[0]["id"]
    # the console's CheckForm rejects the write unless user_id is the
    # collection's actual owner - a bare "Params validation failed." with no
    # field name if it's missing (verified live, see rustdesk_client.py)
    assert rule["user_id"] == console.collections[0]["user_id"]

    # re-running does not pile up duplicate collections or rules
    asyncio.run(service.sync_address_book(db_session))
    assert len(console.collections) == 1 and len(console.rules) == 1


def test_sync_stale_address_book_only_pushes_what_drifted(db_session, monkeypatch) -> None:
    console = FakeConsole()
    console.install(monkeypatch)
    db_session.add(Computer(hostname="VNA-MGR-403", location="A4"))
    db_session.add(Computer(hostname="VNA-MGR-404", location="A4"))
    db_session.commit()
    service.seed_from_inventory(db_session)

    asyncio.run(service.sync_address_book(db_session))
    assert console.creates == 2

    # nothing drifted -> the two-minute worker pass makes no console calls
    console.creates = console.updates = 0
    assert asyncio.run(service.sync_stale_address_book(db_session))["pushed"] == 0
    assert console.creates == 0 and console.updates == 0

    # rotate one password: only that row is re-pushed
    service.rotate_password(db_session, _dev(db_session, "VNA-MGR-403"))
    assert asyncio.run(service.sync_stale_address_book(db_session))["pushed"] == 1
    assert console.updates == 1


def test_provision_account_returns_the_password_but_never_stores_it(db_session, monkeypatch) -> None:
    console = FakeConsole()
    console.install(monkeypatch)

    account, secret = asyncio.run(service.provision_account(db_session, username="ivanov"))
    assert len(secret) >= 12
    assert console.passwords[account.console_user_id] == secret
    # the engineer lands in the group the shared book is shared with
    ivanov = next(u for u in console.users if u["username"] == "ivanov")
    assert ivanov["group_id"] == console.groups[0]["id"]
    assert account.book_shared is True and account.active is True
    # the secret exists nowhere on the row, and the model has no field for it
    assert secret not in str(account.model_dump())
    assert not any("password" in f for f in type(account).model_fields)


def test_provision_account_is_idempotent_for_an_existing_username(db_session, monkeypatch) -> None:
    console = FakeConsole()
    console.install(monkeypatch)

    asyncio.run(service.provision_account(db_session, username="ivanov"))
    _, second = asyncio.run(service.provision_account(db_session, username="ivanov"))

    # re-running resets the password rather than failing on a duplicate user -
    # still just the seeded service account plus the one ivanov row
    assert len(console.users) == 2
    ivanov_id = next(u for u in console.users if u["username"] == "ivanov")["id"]
    assert console.passwords[ivanov_id] == second
    rows = db_session.exec(
        select(RemoteAccessConsoleAccount).where(RemoteAccessConsoleAccount.username == "ivanov")
    ).all()
    assert len(rows) == 1


def test_sync_accounts_picks_up_logins_created_in_the_console(db_session, monkeypatch) -> None:
    console = FakeConsole()
    console.install(monkeypatch)
    console.users.append(
        {"id": 42, "username": "petrov", "is_admin": True, "email": "p@x", "status": 2}
    )

    res = asyncio.run(service.sync_accounts(db_session))
    # the seeded service account counts too - sync_accounts mirrors everyone
    # the console lists, not just the ones InfraScope provisioned
    assert res["accounts_seen"] == 2

    row = db_session.exec(
        select(RemoteAccessConsoleAccount).where(RemoteAccessConsoleAccount.username == "petrov")
    ).first()
    assert row.console_user_id == 42 and row.is_admin is True
    assert row.active is False  # status 2 == disabled in the console
