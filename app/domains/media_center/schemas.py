from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

MediaKind = Literal["stream", "video", "audio"]
PlaybackMode = Literal["loop", "once", "scheduled"]
PlayerState = Literal["idle", "disabled", "playing", "error", "unknown"]


class MediaAssignmentCreate(BaseModel):
    title: str
    media_type: MediaKind = "stream"
    source_url: str
    asset_id: uuid.UUID | None = None
    playback_mode: PlaybackMode = "loop"
    volume: int | None = None
    enabled: bool = True

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        title = value.strip()
        if not title or len(title) > 255:
            raise ValueError("title must be 1-255 characters")
        return title

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        source = value.strip()
        if not source or len(source) > 2048:
            raise ValueError("source_url must be 1-2048 characters")
        if "://" not in source and not source.startswith("/"):
            raise ValueError("source_url must be URL or absolute path")
        return source

    @field_validator("volume")
    @classmethod
    def validate_volume(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value < 0 or value > 100:
            raise ValueError("volume must be between 0 and 100")
        return value


class MediaAssignmentUpdate(BaseModel):
    title: str | None = None
    media_type: MediaKind | None = None
    source_url: str | None = None
    asset_id: uuid.UUID | None = None
    playback_mode: PlaybackMode | None = None
    volume: int | None = None
    enabled: bool | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        title = value.strip()
        if not title or len(title) > 255:
            raise ValueError("title must be 1-255 characters")
        return title

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        source = value.strip()
        if not source or len(source) > 2048:
            raise ValueError("source_url must be 1-2048 characters")
        if "://" not in source and not source.startswith("/"):
            raise ValueError("source_url must be URL or absolute path")
        return source

    @field_validator("volume")
    @classmethod
    def validate_volume(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value < 0 or value > 100:
            raise ValueError("volume must be between 0 and 100")
        return value


class MediaAssignmentPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    player_id: uuid.UUID
    asset_id: uuid.UUID | None = None
    title: str
    media_type: str
    source_url: str
    playback_mode: str
    volume: int | None = None
    enabled: bool
    revision: int
    created_at: datetime
    updated_at: datetime | None = None


class MediaAssignmentsPublic(BaseModel):
    data: list[MediaAssignmentPublic]
    count: int


class MediaAssetPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    media_type: str
    source_url: str
    original_filename: str | None = None
    content_type: str | None = None
    file_size_bytes: int | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime | None = None


class MediaAssetsPublic(BaseModel):
    data: list[MediaAssetPublic]
    count: int


class MediaClientHeartbeatPayload(BaseModel):
    agent_version: str | None = None
    hostname: str | None = None
    current_revision: int | None = None
    player_state: PlayerState = "unknown"
    error_message: str | None = None

    @field_validator("agent_version", "hostname", "error_message")
    @classmethod
    def trim_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

    @field_validator("current_revision")
    @classmethod
    def validate_revision(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("current_revision must be non-negative")
        return value


class MediaClientHeartbeatPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    player_id: uuid.UUID
    agent_version: str | None = None
    hostname: str | None = None
    current_revision: int | None = None
    player_state: str
    error_message: str | None = None
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime | None = None


class MediaClientHeartbeatsPublic(BaseModel):
    data: list[MediaClientHeartbeatPublic]
    count: int


class MediaClientManifest(BaseModel):
    device_id: str
    revision: int
    enabled: bool
    title: str | None = None
    media_type: str | None = None
    source_url: str | None = None
    playback_mode: str = "loop"
    volume: int | None = None
