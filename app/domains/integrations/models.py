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


class HonestSignStatusRecord(SQLModel, table=True):
    """Last Local Module status the scheduled check saw for one register.

    Keyed by the target's original (env-configured) host, like the override
    table, so it survives IP overrides. `host` is the IP that was actually
    checked: a record whose host no longer matches the target is stale.
    `problem_reported` is the alert latch - set when the event log got a
    "down" entry, cleared (with a "recovered" entry) on the next ready check -
    so a register that stays broken is reported once, not every cycle.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    original_host: str = Field(max_length=45, unique=True, index=True)
    host: str = Field(max_length=45)
    reachable: bool
    status: str = Field(max_length=64)
    version: str | None = Field(default=None, max_length=64)
    ready: bool
    message: str = Field(default="", max_length=255)
    checked_at: datetime
    state_since: datetime
    consecutive_failures: int = Field(default=0)
    problem_reported: bool = Field(default=False)
