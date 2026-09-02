from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "DevicePublic",
    "DevicesPublic",
    "DeviceDesiredUpdate",
    "DeviceEnsureRequest",
    "AddressBookSyncRequest",
    "PackageConfig",
    "AddressBookEntry",
    "AddressBookUpsert",
    "ConsoleUser",
    "ConnectionRecord",
]

_HOSTNAME_RE = r"^[A-Za-z0-9._-]{1,255}$"


def _validate_rid(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    if len(v) > 32 or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_" for c in v):
        raise ValueError("rustdesk_id must be <=32 chars of [A-Za-z0-9_]")
    return v


# --------------------------------------------------------------------------- #
# managed devices                                                            #
# --------------------------------------------------------------------------- #
class DevicePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hostname: str
    location: str | None = None
    source_kind: str = "computer"
    computer_id: uuid.UUID | None = None
    media_player_id: uuid.UUID | None = None
    cash_register_id: uuid.UUID | None = None
    rustdesk_id: str | None = None
    has_password: bool = False  # InfraScope holds the password the KSC package should carry
    password_rotated_at: datetime | None = None
    desired_hidden: bool
    desired_block_outgoing: bool
    desired_unattended: bool
    managed: bool
    in_address_book: bool = False
    installed_version: str | None = None
    online: bool | None = None  # RustDesk console: client reachable via rendezvous
    logged_in_user: str | None = None
    last_ip: str | None = None
    last_seen_at: datetime | None = None
    host_online: bool | None = None  # InfraScope: host answers a reachability probe
    host_last_seen_at: datetime | None = None
    created_at: datetime


class DevicesPublic(BaseModel):
    data: list[DevicePublic]
    count: int


class DeviceDesiredUpdate(BaseModel):
    desired_hidden: bool | None = None
    desired_block_outgoing: bool | None = None
    desired_unattended: bool | None = None
    managed: bool | None = None
    location: str | None = None
    rustdesk_id: str | None = None

    @field_validator("rustdesk_id")
    @classmethod
    def _rid(cls, v: str | None) -> str | None:
        return _validate_rid(v)


class DeviceEnsureRequest(BaseModel):
    """Create/link a device row and stamp its desired id + password.

    Backs the "Настроить RustDesk" button on the computer / cash-register /
    media-player cards. Records config only - nothing is applied to the machine.
    """

    hostname: str = Field(pattern=_HOSTNAME_RE)
    rustdesk_id: str | None = None
    permanent_password: str | None = Field(default=None, max_length=128)

    @field_validator("rustdesk_id")
    @classmethod
    def _rid(cls, v: str | None) -> str | None:
        return _validate_rid(v)

    @field_validator("permanent_password")
    @classmethod
    def _pw(cls, v: str | None) -> str | None:
        return v.strip() or None if v is not None else None


class AddressBookSyncRequest(BaseModel):
    # optional narrowing; empty means all managed devices
    device_ids: list[uuid.UUID] | None = None
    location: str | None = None
    source_kind: str | None = Field(default=None, pattern=r"^(cash_register|computer|media_player)$")


class PackageConfig(BaseModel):
    """What the KSC post-install step (`rustdesk-ksc/configure.ps1`) needs."""

    hostname: str
    rustdesk_id: str
    id_server: str
    relay_server: str
    api_server: str
    key: str
    permanent_password: str
    installer_version: str
    hidden: bool
    block_outgoing: bool
    unattended: bool


# --------------------------------------------------------------------------- #
# console passthrough (shapes we re-expose; loose on purpose)                 #
# --------------------------------------------------------------------------- #
class AddressBookEntry(BaseModel):
    id: str
    alias: str | None = None
    hostname: str | None = None
    username: str | None = None
    platform: str | None = None
    tags: list[str] = []
    online: bool | None = None


class AddressBookUpsert(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    alias: str | None = None
    tags: list[str] = []
    force_always_relay: bool = False


class ConsoleUser(BaseModel):
    id: int | None = None
    username: str
    is_admin: bool | None = None
    status: int | None = None


class ConnectionRecord(BaseModel):
    id: int | None = None
    from_peer: str | None = None
    from_name: str | None = None
    peer_id: str | None = None
    ip: str | None = None
    action: str | None = None
    created_at: str | None = None
    close_time: str | None = None
