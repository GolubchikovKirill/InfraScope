from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from app.core.crypto import EncryptedString

# ---------------------------------------------------------------------------
# deploy state machine
#   unknown       - never contacted / just created
#   not_installed - agent confirmed RustDesk absent
#   installing    - a deploy job is in flight
#   installed     - binary present, config not yet ours
#   configured    - our server + hostname id + password + lockdown all applied
#   drift         - agent reports the on-disk config no longer matches desired
#   failed        - last job failed (see last_error)
#   uninstalled   - agent confirmed removal
# ---------------------------------------------------------------------------
DEPLOY_STATES = (
    "unknown",
    "not_installed",
    "installing",
    "installed",
    "configured",
    "drift",
    "failed",
    "uninstalled",
)

JOB_ACTIONS = ("deploy", "reconfigure", "rotate_password", "set_lockdown", "uninstall")
JOB_STATUSES = ("queued", "claimed", "running", "done", "failed", "cancelled")


class RemoteAccessDevice(SQLModel, table=True):
    """One managed RustDesk endpoint, keyed by hostname and linked to inventory."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hostname: str = Field(max_length=255, unique=True, index=True)

    # soft links to the inventory rows this endpoint corresponds to (either may be set)
    computer_id: uuid.UUID | None = Field(default=None, foreign_key="computer.id", index=True)
    media_player_id: uuid.UUID | None = Field(default=None, foreign_key="mediaplayer.id", index=True)
    location: str | None = Field(default=None, max_length=128, index=True)

    # --- desired config (what the agent should converge the endpoint to) ---
    rustdesk_id: str | None = Field(default=None, max_length=32, index=True)
    # per-machine, rotatable from InfraScope; encrypted at rest (see NetworkSwitch.ssh_password)
    permanent_password: str = Field(
        default="", sa_column=Column(EncryptedString(512), nullable=False, server_default="")
    )
    password_rotated_at: datetime | None = Field(default=None)
    desired_hidden: bool = Field(default=True)  # hide-tray + strip Start Menu/Desktop shortcuts
    desired_block_outgoing: bool = Field(default=True)  # AppLocker: no interactive rustdesk.exe for non-admins
    desired_unattended: bool = Field(default=True)  # approve-mode=password (no on-screen accept)
    managed: bool = Field(default=True, index=True)  # unset to stop InfraScope from touching it

    # --- observed state ---
    deploy_state: str = Field(default="unknown", max_length=16, index=True)
    deploy_detail: str | None = Field(default=None, max_length=512)
    installed_version: str | None = Field(default=None, max_length=32)
    online: bool | None = Field(default=None, index=True)
    logged_in_user: str | None = Field(default=None, max_length=128)
    last_ip: str | None = Field(default=None, max_length=64)
    last_seen_at: datetime | None = Field(default=None, index=True)  # from the console peer list
    last_deployed_at: datetime | None = Field(default=None)
    last_error: str | None = Field(default=None, max_length=1024)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    updated_at: datetime | None = Field(default=None)


class RemoteAccessDeployJob(SQLModel, table=True):
    """A unit of work for the Windows deploy agent (claim -> run -> report)."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    device_id: uuid.UUID = Field(foreign_key="remoteaccessdevice.id", index=True)
    hostname: str = Field(max_length=255, index=True)  # denormalized so the agent needn't resolve

    action: str = Field(max_length=24, index=True)
    # non-secret params only (installer version, lockdown flags, server addrs...).
    # the permanent password is fetched separately via the agent secret endpoint.
    params: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))

    status: str = Field(default="queued", max_length=16, index=True)
    attempts: int = Field(default=0)
    claimed_by: str | None = Field(default=None, max_length=128)
    claimed_at: datetime | None = Field(default=None)
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)
    result_detail: str | None = Field(default=None, max_length=2048)

    created_by: str | None = Field(default=None, max_length=255)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    updated_at: datetime | None = Field(default=None)
