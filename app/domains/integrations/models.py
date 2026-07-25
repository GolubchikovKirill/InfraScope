from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class HonestSignTargetOverride(SQLModel, table=True):
    """A manual IP override for a Honest Sign target configured in
    HONEST_SIGN_TARGETS (app.core.config.settings).

    Cash registers occasionally get a new IP (DHCP reservation change,
    replacement) without the store's naming/label changing. Editing the
    server .env for a single IP change is slow; this table lets an operator
    redirect a target to its current IP from the app instead. Keyed by the
    target's original (env-configured) host, which stays stable across
    repeated edits.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    original_host: str = Field(max_length=45, unique=True, index=True)
    current_host: str = Field(max_length=45)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = Field(default=None)
