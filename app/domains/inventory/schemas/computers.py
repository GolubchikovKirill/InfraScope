from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

__all__ = ["ComputerCreate", "ComputerUpdate", "ComputerPublic", "ComputersPublic"]


class ComputerCreate(BaseModel):
    hostname: str
    location: str | None = None
    comment: str | None = None

    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, v: str) -> str:
        value = v.strip()
        if not value or len(value) > 255:
            raise ValueError("hostname must be 1-255 characters")
        return value

    @field_validator("location", "comment")
    @classmethod
    def normalize_optional_text(cls, v: str | None) -> str | None:
        if v is None:
            return None
        value = v.strip()
        if not value:
            return None
        if len(value) > 1024:
            raise ValueError("Field is too long")
        return value


class ComputerUpdate(BaseModel):
    hostname: str | None = None
    location: str | None = None
    comment: str | None = None

    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, v: str | None) -> str | None:
        if v is None:
            return None
        value = v.strip()
        if not value or len(value) > 255:
            raise ValueError("hostname must be 1-255 characters")
        return value

    @field_validator("location", "comment")
    @classmethod
    def normalize_optional_text(cls, v: str | None) -> str | None:
        if v is None:
            return None
        value = v.strip()
        if not value:
            return None
        if len(value) > 1024:
            raise ValueError("Field is too long")
        return value


class ComputerPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hostname: str
    location: str | None = None
    comment: str | None = None
    is_online: bool | None = None
    reachability_reason: str | None = None
    last_polled_at: datetime | None = None
    created_at: datetime


class ComputersPublic(BaseModel):
    data: list[ComputerPublic]
    count: int
