import uuid
from datetime import UTC, datetime

from sqlalchemy import Index
from sqlmodel import Field, SQLModel


class SoftwareAgent(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hostname: str = Field(max_length=255, index=True)
    token_hash: str = Field(max_length=255, index=True, unique=True)
    agent_version: str = Field(max_length=32, index=True)
    os_version: str | None = Field(default=None, max_length=128)
    architecture: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=1024)
    last_seen_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    revoked_at: datetime | None = Field(default=None, index=True)

    __table_args__ = (Index("ix_agent_hostname_version", "hostname", "agent_version"),)
