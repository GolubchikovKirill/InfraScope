from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "CATEGORIES",
    "CredentialPublic",
    "CredentialsPublic",
    "CredentialCreate",
    "CredentialUpdate",
    "CredentialSecret",
    "PasswordGenerateRequest",
    "PasswordGenerateResponse",
]

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

_CATEGORY_RE = r"^(switch|printer|cash_register|computer|media_player|camera|server|service|website|other)$"


def _clean(v: str | None, *, limit: int) -> str | None:
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    if len(v) > limit:
        raise ValueError(f"value must be <= {limit} characters")
    return v


class CredentialPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    category: str = "other"
    username: str | None = None
    has_secret: bool = False  # the plaintext secret is only served by /reveal
    host: str | None = None
    location: str | None = None
    url: str | None = None
    notes: str | None = None
    tags: str | None = None
    secret_rotated_at: datetime | None = None
    created_by_id: uuid.UUID | None = None
    updated_by_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime | None = None


class CredentialsPublic(BaseModel):
    data: list[CredentialPublic]
    count: int


class CredentialCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    category: str = Field(default="other", pattern=_CATEGORY_RE)
    username: str | None = Field(default=None, max_length=255)
    secret: str = Field(min_length=1, max_length=1024)
    host: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=128)
    url: str | None = Field(default=None, max_length=512)
    notes: str | None = Field(default=None, max_length=4096)
    tags: str | None = Field(default=None, max_length=512)

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title is required")
        return v

    @field_validator("username", "host", "location", "url", "notes", "tags")
    @classmethod
    def _optional(cls, v: str | None) -> str | None:
        return v.strip() or None if v is not None else None


class CredentialUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, pattern=_CATEGORY_RE)
    username: str | None = Field(default=None, max_length=255)
    # only re-encrypted when a non-empty value is sent; blank/absent leaves the
    # stored secret untouched
    secret: str | None = Field(default=None, max_length=1024)
    host: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=128)
    url: str | None = Field(default=None, max_length=512)
    notes: str | None = Field(default=None, max_length=4096)
    tags: str | None = Field(default=None, max_length=512)

    @field_validator("title")
    @classmethod
    def _title(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("title cannot be blank")
        return v


class CredentialSecret(BaseModel):
    """Response of /reveal - the decrypted secret, plus the notes for convenience."""

    id: uuid.UUID
    secret: str
    notes: str | None = None


class PasswordGenerateRequest(BaseModel):
    length: int = Field(default=20, ge=8, le=128)
    uppercase: bool = True
    lowercase: bool = True
    digits: bool = True
    symbols: bool = True
    # drop visually confusable characters (I l 1 O 0 o 5 S 2 Z 8 B)
    exclude_ambiguous: bool = False
    exclude_chars: str = Field(default="", max_length=64)
    # guarantee at least one character from every enabled class
    min_of_each: bool = True


class PasswordGenerateResponse(BaseModel):
    password: str
    entropy_bits: float
