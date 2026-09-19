from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "DevicePublic",
    "DevicesPublic",
    "DeviceDesiredUpdate",
    "DeviceProfileUpdate",
    "DeviceEnsureRequest",
    "AddressBookSyncRequest",
    "AddressBookStatus",
    "PackageConfig",
    "DeploymentConfig",
    "DeployConfigRequest",
    "DeployReport",
    "DeployCommand",
    "ConsoleAccountPublic",
    "ConsoleAccountsPublic",
    "ConsoleAccountCreate",
    "ConsoleAccountSecret",
    "ConsoleAccountPasswordReset",
    "ConsoleUser",
    "ConnectionRecord",
    "AddressBookEntry",
]

_HOSTNAME_RE = r"^[A-Za-z0-9._-]{1,255}$"
_USERNAME_RE = r"^[A-Za-z0-9._-]{2,32}$"


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
    # role token read off the hostname itself (VNA-KKM-1506 -> "KKM") - the
    # same one that lands as an extra tag in the shared address book, see
    # service.hostname_type_tag. None for names that don't fit the pattern.
    type_tag: str | None = None
    computer_id: uuid.UUID | None = None
    media_player_id: uuid.UUID | None = None
    cash_register_id: uuid.UUID | None = None
    rustdesk_id: str | None = None
    has_password: bool = False  # InfraScope holds the password the rollout will apply
    password_rotated_at: datetime | None = None
    deploy_profile: str = "client"  # "client" | "admin" - see service.DEPLOY_PROFILES
    desired_hidden: bool
    desired_block_outgoing: bool
    desired_unattended: bool
    managed: bool
    in_address_book: bool = False
    ab_password_pushed: bool = False
    # rollout, as reported by the endpoint itself
    deploy_state: str = "unknown"
    deploy_detail: str | None = None
    deploy_requested_at: datetime | None = None
    deploy_reported_at: datetime | None = None
    # single chip for the UI: ready | installed_offline | deploying | failed | not_deployed
    readiness: str = "not_deployed"
    installed_version: str | None = None
    os_edition: str | None = None  # raw registry EditionID, self-reported by the endpoint
    os_caption: str | None = None  # e.g. "Windows 10 Pro", for display
    applocker_supported: bool | None = None  # None until the machine has reported
    # true only when we asked for block_outgoing AND know it silently did not
    # apply - never true while applocker_supported is still unknown
    applocker_mismatch: bool = False
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


class DeviceProfileUpdate(BaseModel):
    """Sets desired_hidden/desired_block_outgoing/desired_unattended together
    from a named preset (service.DEPLOY_PROFILES), instead of an operator
    having to get all three booleans right by hand for the common case."""

    profile: str = Field(pattern=r"^(client|admin)$")


class DeviceEnsureRequest(BaseModel):
    """Create/link a device row and stamp its desired id + password.

    Backs the "Настроить RustDesk" button on the computer / cash-register /
    media-player cards. Records config only - nothing is applied to the machine
    until the rollout script runs there.
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


class UnlistedPeerPublic(BaseModel):
    """A machine the RustDesk console knows that InfraScope does not track."""

    hostname: str
    rustdesk_id: str | None = None
    os: str | None = None
    version: str | None = None
    username: str | None = None
    online: bool = False
    last_online: datetime | None = None
    # "admin" for an engineer workstation (VNK-ITD-*), "client" for everything
    # else - the same split DEPLOY_PROFILES documents. Only a suggestion.
    suggested_profile: str = "client"


class UnlistedPeersPublic(BaseModel):
    data: list[UnlistedPeerPublic]
    count: int
    # peers the console lists with no hostname at all (factory numeric ids that
    # never reported one) - they cannot be named here, so they are only counted
    nameless_peers: int = 0
    console_reachable: bool = True


class PeerAdoptRequest(BaseModel):
    """Put a console machine under InfraScope management."""

    hostname: str = Field(pattern=_HOSTNAME_RE)
    profile: str | None = Field(default=None, pattern=r"^(client|admin)$")


class PeerDismissRequest(BaseModel):
    """Stop offering a console machine (a personal laptop, a test box...)."""

    hostname: str = Field(pattern=_HOSTNAME_RE)


class AddressBookSyncRequest(BaseModel):
    # optional narrowing; empty means all managed devices
    device_ids: list[uuid.UUID] | None = None
    location: str | None = None
    source_kind: str | None = Field(default=None, pattern=r"^(cash_register|computer|media_player)$")


class AddressBookStatus(BaseModel):
    name: str
    collection_id: int
    owner_user_id: int
    entries: int
    shared_with_group: str
    accounts: int
    # devices InfraScope believes are in the book but the console doesn't
    # actually have right now - see service.address_book_status. Normally 0.
    missing: int = 0


class PackageConfig(BaseModel):
    """What an offline KSC package needs (`rustdesk-ksc/configure.ps1`)."""

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
# rollout                                                                     #
# --------------------------------------------------------------------------- #
class DeployConfigRequest(BaseModel):
    hostname: str = Field(pattern=_HOSTNAME_RE)


class DeploymentConfig(PackageConfig):
    """What the endpoint script pulls for itself at run time.

    `options` goes into `[options]` before the password is set; `lock_options`
    only afterwards - `disable-change-permanent-password` would otherwise make
    `rustdesk.exe --password` a no-op.
    """

    installer_filename: str
    installer_sha256: str
    options: dict[str, str]
    lock_options: dict[str, str]


class DeployReport(BaseModel):
    """What the endpoint script says it did. Stored verbatim.

    `os_edition`/`os_caption` are the endpoint's own registry EditionID and
    OS caption - self-reported because InfraScope has no other channel to
    learn this without a new remote-query surface. The server, not the
    script, classifies edition into `applocker_supported` (see
    service.classify_applocker_support) so that logic stays in one testable
    place.
    """

    hostname: str = Field(pattern=_HOSTNAME_RE)
    state: str = Field(pattern=r"^(pending|installed|configured|failed)$")
    rustdesk_id: str | None = None
    version: str | None = Field(default=None, max_length=32)
    detail: str | None = Field(default=None, max_length=512)
    os_edition: str | None = Field(default=None, max_length=64)
    os_caption: str | None = Field(default=None, max_length=128)

    @field_validator("rustdesk_id")
    @classmethod
    def _rid(cls, v: str | None) -> str | None:
        return _validate_rid(v)


class DeployCommand(BaseModel):
    """The one line an operator pastes into KSC / GPO / schtasks."""

    command: str
    bootstrap_url: str
    installer_filename: str
    installer_version: str
    configured: bool  # false when RUSTDESK_DEPLOY_TOKEN / PUBLIC_URL are unset


# --------------------------------------------------------------------------- #
# console accounts                                                            #
# --------------------------------------------------------------------------- #
class ConsoleAccountPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    console_user_id: int | None = None
    display_name: str | None = None
    email: str | None = None
    is_admin: bool = False
    infrascope_user_id: uuid.UUID | None = None
    active: bool = True
    book_shared: bool = False
    last_synced_at: datetime | None = None
    created_at: datetime


class ConsoleAccountsPublic(BaseModel):
    data: list[ConsoleAccountPublic]
    count: int


class ConsoleAccountCreate(BaseModel):
    username: str = Field(pattern=_USERNAME_RE)
    display_name: str | None = Field(default=None, max_length=128)
    email: str | None = Field(default=None, max_length=255)
    is_admin: bool = False
    # left empty a strong one is generated; either way it is shown exactly once
    password: str | None = Field(default=None, min_length=8, max_length=64)
    infrascope_user_id: uuid.UUID | None = None


class ConsoleAccountPasswordReset(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=64)


class ConsoleAccountSecret(BaseModel):
    """Create/reset response. `password` is shown once and never stored."""

    account: ConsoleAccountPublic
    password: str
    note: str = "Пароль показывается один раз и не хранится в InfraScope."


# --------------------------------------------------------------------------- #
# console passthrough (shapes we re-expose; loose on purpose)                 #
# --------------------------------------------------------------------------- #
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


class AddressBookEntry(BaseModel):
    id: str
    alias: str | None = None
    hostname: str | None = None
    username: str | None = None
    platform: str | None = None
    tags: list[Any] = []
    online: bool | None = None
