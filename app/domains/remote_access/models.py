from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from app.core.crypto import EncryptedString

# which InfraScope inventory table an endpoint was seeded from
SOURCE_KINDS = ("cash_register", "computer", "media_player")


class RemoteAccessDevice(SQLModel, table=True):
    """One RustDesk endpoint InfraScope tracks, keyed by hostname and linked to inventory.

    Holds the *desired* config the endpoint should end up with (id, password,
    lockdown switches), the *reported* rollout state the endpoint's own script
    sent back, and the *observed* status folded in from the RustDesk console and
    InfraScope's own reachability polling. The three are kept apart on purpose -
    "we asked for it", "the machine says it did it" and "the console sees it" are
    different facts and the UI shows them as such.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # Uniqueness lives on a functional index over lower(hostname), not this
    # column directly - every lookup in this domain is case-insensitive
    # (Windows hostnames are), see migration a0b1c2d3e4f5 and
    # service._get_or_create_device.
    hostname: str = Field(max_length=255)

    # soft links to the inventory rows this endpoint corresponds to (any subset may be set:
    # a till tracked both as a CashRegister and a Computer links to both)
    computer_id: uuid.UUID | None = Field(default=None, foreign_key="computer.id", index=True)
    media_player_id: uuid.UUID | None = Field(default=None, foreign_key="mediaplayer.id", index=True)
    cash_register_id: uuid.UUID | None = Field(default=None, foreign_key="cashregister.id", index=True)
    # cash_register | computer | media_player - the strongest inventory source that owns this host
    source_kind: str = Field(default="computer", max_length=16, index=True)
    location: str | None = Field(default=None, max_length=128, index=True)

    # --- desired config the KSC package should carry ---
    rustdesk_id: str | None = Field(default=None, max_length=32, index=True)
    # the permanent password baked into the package for this machine; encrypted at rest
    permanent_password: str = Field(
        default="", sa_column=Column(EncryptedString(512), nullable=False, server_default="")
    )
    password_rotated_at: datetime | None = Field(default=None)
    # "client" | "admin" - which preset last set the three flags below. New
    # devices default to "client": most of the fleet is store kiosks/kassa
    # that must never be self-usable. A machine an engineer sits at (their own
    # workstation) needs the opposite of every one of these - see
    # service.DEPLOY_PROFILES. Purely a UI/bulk-action convenience: the three
    # flags are what the rollout script actually reads, this just names the
    # combination so an operator doesn't have to get all three right by hand.
    deploy_profile: str = Field(default="client", max_length=16, index=True)
    desired_hidden: bool = Field(default=True)  # hide-tray + strip Start Menu/Desktop shortcuts
    desired_block_outgoing: bool = Field(default=True)  # AppLocker: no interactive rustdesk.exe for non-admins
    desired_unattended: bool = Field(default=True)  # approve-mode=password (no on-screen accept)
    managed: bool = Field(default=True, index=True)  # unset to stop InfraScope from tracking it

    # --- shared address book ---
    in_address_book: bool = Field(default=False, index=True)  # present in the shared console book
    ab_row_id: int | None = Field(default=None)  # console row id, so we update instead of re-adding
    ab_password_pushed: bool = Field(default=False)  # the book row carries the current password

    # --- rollout, as reported by the endpoint's own script ---
    # unknown -> pending -> installed -> configured | failed
    deploy_state: str = Field(default="unknown", max_length=16, index=True)
    deploy_detail: str | None = Field(default=None, max_length=512)
    deploy_requested_at: datetime | None = Field(default=None)
    deploy_reported_at: datetime | None = Field(default=None)

    # --- observed status ---
    installed_version: str | None = Field(default=None, max_length=32)
    # self-reported by the endpoint script (registry EditionID: "Professional",
    # "Enterprise", "Core" for Home, ...) - InfraScope has no other channel to
    # learn this without a new remote-query surface, so it is only known for
    # machines that have run the rollout script at least once.
    os_edition: str | None = Field(default=None, max_length=64)
    os_caption: str | None = Field(default=None, max_length=128)  # e.g. "Windows 10 Pro", for display
    # derived from os_edition: does this Windows edition support AppLocker at
    # all. None until the machine has reported; block_outgoing silently does
    # nothing on a machine where this is False.
    applocker_supported: bool | None = Field(default=None, index=True)
    # RustDesk-console truth: is the client itself reachable via the rendezvous server
    online: bool | None = Field(default=None, index=True)
    logged_in_user: str | None = Field(default=None, max_length=128)
    last_ip: str | None = Field(default=None, max_length=64)
    last_seen_at: datetime | None = Field(default=None, index=True)  # from the console peer list
    # InfraScope-inventory truth: does the host answer a plain reachability probe.
    # kept separate so the UI never passes "host pings" off as "RustDesk connected"
    host_online: bool | None = Field(default=None, index=True)
    host_last_seen_at: datetime | None = Field(default=None)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    updated_at: datetime | None = Field(default=None)


class RemoteAccessConsoleAccount(SQLModel, table=True):
    """A RustDesk console login InfraScope provisions for an engineer.

    Every account lands in the console group named by RUSTDESK_ADMIN_GROUP_NAME,
    which the shared address book is shared with - so a new engineer sees the
    whole fleet the moment they log into their RustDesk client, with no per-user
    address-book push.

    The password is deliberately **not** stored: it is generated, handed to the
    console, and returned exactly once in the create/reset response. Losing it
    means resetting it, not reading it back.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    username: str = Field(max_length=64, unique=True, index=True)
    console_user_id: int | None = Field(default=None, index=True)
    display_name: str | None = Field(default=None, max_length=128)
    email: str | None = Field(default=None, max_length=255)
    is_admin: bool = Field(default=False)
    # optional link to the InfraScope operator this console login belongs to
    infrascope_user_id: uuid.UUID | None = Field(default=None, foreign_key="user.id", index=True)
    active: bool = Field(default=True, index=True)
    book_shared: bool = Field(default=False)  # the shared-book rule has been granted
    last_synced_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    updated_at: datetime | None = Field(default=None)
