from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from app.core.crypto import EncryptedString

# free-form label only - no foreign keys into the inventory tables. Kept in sync
# with CATEGORIES in schemas.py and CredentialCategory on the frontend.
CATEGORIES = (
    "switch",
    "printer",
    "cash_register",
    "computer",
    "media_player",
    "camera",
    "server",
    "service",
    "website",
    "other",
)


class Credential(SQLModel, table=True):
    """One stored login/secret for a piece of infrastructure.

    `secret` and `notes` are encrypted at rest via EncryptedString (same
    mechanism as switch SSH passwords and RemoteAccessDevice.permanent_password);
    callers read and write plain strings. Everything else is plaintext and
    searchable. The row records who created and last touched it, but the secret
    itself is only ever handed out through the audited /reveal route.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    title: str = Field(max_length=200, index=True)
    category: str = Field(default="other", max_length=32, index=True)
    username: str | None = Field(default=None, max_length=255)
    secret: str = Field(
        default="", sa_column=Column(EncryptedString(1024), nullable=False, server_default="")
    )
    # free text: IP, hostname or URL - deliberately not linked to inventory rows
    host: str | None = Field(default=None, max_length=255, index=True)
    location: str | None = Field(default=None, max_length=128, index=True)
    url: str | None = Field(default=None, max_length=512)
    # notes can carry a secondary secret (recovery codes, a second account), so
    # they are encrypted too
    notes: str | None = Field(default=None, sa_column=Column(EncryptedString(4096), nullable=True))
    tags: str | None = Field(default=None, max_length=512)  # comma-separated

    secret_rotated_at: datetime | None = Field(default=None)
    created_by_id: uuid.UUID | None = Field(default=None, foreign_key="user.id", index=True)
    updated_by_id: uuid.UUID | None = Field(default=None, foreign_key="user.id")

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    updated_at: datetime | None = Field(default=None)
