from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class MediaAsset(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    title: str = Field(max_length=255, index=True)
    media_type: str = Field(default="stream", max_length=32, index=True)
    source_url: str = Field(max_length=2048)
    original_filename: str | None = Field(default=None, max_length=255)
    stored_filename: str | None = Field(default=None, max_length=255, index=True)
    content_type: str | None = Field(default=None, max_length=255)
    file_size_bytes: int | None = Field(default=None)
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    updated_at: datetime | None = Field(default=None)


class MediaAssignment(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    player_id: uuid.UUID = Field(index=True, unique=True)
    asset_id: uuid.UUID | None = Field(default=None, index=True)
    title: str = Field(default="", max_length=255)
    media_type: str = Field(default="stream", max_length=32)
    source_url: str = Field(default="", max_length=2048)
    playback_mode: str = Field(default="loop", max_length=32)
    volume: int | None = Field(default=None)
    enabled: bool = Field(default=True, index=True)
    revision: int = Field(default=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    updated_at: datetime | None = Field(default=None)


class MediaClientHeartbeat(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    player_id: uuid.UUID = Field(index=True, unique=True)
    agent_version: str | None = Field(default=None, max_length=64)
    hostname: str | None = Field(default=None, max_length=255)
    current_revision: int | None = Field(default=None)
    player_state: str = Field(default="unknown", max_length=32, index=True)
    error_message: str | None = Field(default=None, max_length=1024)
    last_seen_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    updated_at: datetime | None = Field(default=None)
