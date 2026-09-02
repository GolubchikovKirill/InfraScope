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

    InfraScope does not push the client - that is done through Kaspersky Security
    Center with a preconfigured package (see docs/rustdesk-ksc-deployment.md). This
    row holds the *desired* config the package should carry for the machine, plus
    the *observed* status folded in from the RustDesk console and InfraScope's own
    reachability polling.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hostname: str = Field(max_length=255, unique=True, index=True)

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
    desired_hidden: bool = Field(default=True)  # hide-tray + strip Start Menu/Desktop shortcuts
    desired_block_outgoing: bool = Field(default=True)  # AppLocker: no interactive rustdesk.exe for non-admins
    desired_unattended: bool = Field(default=True)  # approve-mode=password (no on-screen accept)
    managed: bool = Field(default=True, index=True)  # unset to stop InfraScope from tracking it
    in_address_book: bool = Field(default=False, index=True)  # pushed into the console's address book

    # --- observed status ---
    installed_version: str | None = Field(default=None, max_length=32)
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
