from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "DevicePublic",
    "DevicesPublic",
    "DeviceDesiredUpdate",
    "DevicePrepareRequest",
    "DevicePrepareResult",
    "DeployJobPublic",
    "DeployJobsPublic",
    "DeployRequest",
    "AgentJobClaim",
    "AgentJobReport",
    "AgentJobSecret",
    "AgentHeartbeat",
    "AddressBookEntry",
    "AddressBookUpsert",
    "ConsoleUser",
    "ConnectionRecord",
]

_HOSTNAME_RE = r"^[A-Za-z0-9._-]{1,255}$"


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
    has_password: bool = False
    password_rotated_at: datetime | None = None
    desired_hidden: bool
    desired_block_outgoing: bool
    desired_unattended: bool
    managed: bool
    deploy_state: str
    deploy_detail: str | None = None
    installed_version: str | None = None
    online: bool | None = None
    logged_in_user: str | None = None
    last_ip: str | None = None
    last_seen_at: datetime | None = None
    last_deployed_at: datetime | None = None
    last_error: str | None = None
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
# deploy jobs                                                                 #
# --------------------------------------------------------------------------- #
class DeployRequest(BaseModel):
    action: str = Field(pattern=r"^(deploy|reconfigure|rotate_password|set_lockdown|uninstall)$")
    # scope: device_ids wins; otherwise location and/or source_kind narrow all_managed
    device_ids: list[uuid.UUID] | None = None
    location: str | None = None
    source_kind: str | None = Field(default=None, pattern=r"^(cash_register|computer|media_player)$")
    all_managed: bool = False


class DeployJobPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    device_id: uuid.UUID
    hostname: str
    action: str
    status: str
    attempts: int
    claimed_by: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result_detail: str | None = None
    created_by: str | None = None
    created_at: datetime


class DeployJobsPublic(BaseModel):
    data: list[DeployJobPublic]
    count: int


class DevicePrepareRequest(BaseModel):
    """Point-and-shoot: create/link the endpoint, set its id + password, queue a deploy.

    Used by the RustDesk buttons on the computer / cash-register / media-player cards.
    """

    hostname: str = Field(pattern=_HOSTNAME_RE)
    rustdesk_id: str | None = None
    permanent_password: str | None = Field(default=None, max_length=128)
    action: str = Field(default="deploy", pattern=r"^(deploy|reconfigure)$")

    @field_validator("rustdesk_id")
    @classmethod
    def _rid(cls, v: str | None) -> str | None:
        return _validate_rid(v)

    @field_validator("permanent_password")
    @classmethod
    def _pw(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip() or None


class DevicePrepareResult(BaseModel):
    device: DevicePublic
    job: DeployJobPublic | None = None


# --------------------------------------------------------------------------- #
# Windows deploy-agent protocol                                              #
# --------------------------------------------------------------------------- #
class AgentHeartbeat(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    version: str | None = None
    hostname: str | None = None


class AgentJobClaim(BaseModel):
    """One job handed to the agent. Non-secret; call the secret endpoint for the password."""

    job_id: uuid.UUID
    device_id: uuid.UUID
    hostname: str
    action: str
    params: dict
    rustdesk_id: str | None = None
    id_server: str
    relay_server: str
    key: str
    installer_version: str
    desired_hidden: bool
    desired_block_outgoing: bool
    desired_unattended: bool


class AgentJobSecret(BaseModel):
    permanent_password: str


class AgentJobReport(BaseModel):
    status: str = Field(pattern=r"^(running|done|failed)$")
    detail: str | None = Field(default=None, max_length=2048)
    # observed facts the agent learned while running
    installed_version: str | None = None
    rustdesk_id: str | None = None
    deploy_state: str | None = None


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
