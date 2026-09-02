"""add_remote_access (RustDesk wrapper: managed devices + deploy jobs)

Revision ID: f1a2b3c4d5e6
Revises: e8f9a0b1c2d3
Create Date: 2026-09-02 12:00:00.000000

Two tables backing app.domains.remote_access:

* remoteaccessdevice - one managed RustDesk endpoint per hostname, soft-linked to
  computer/mediaplayer, holding desired config + observed state. permanent_password
  is written through app.core.crypto.EncryptedString (same as networkswitch.ssh_password),
  so the column is plain VARCHAR here.
* remoteaccessdeployjob - claim/run/report queue for the Windows deploy agent.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "e8f9a0b1c2d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "remoteaccessdevice",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("computer_id", sa.Uuid(), nullable=True),
        sa.Column("media_player_id", sa.Uuid(), nullable=True),
        sa.Column("location", sa.String(length=128), nullable=True),
        sa.Column("rustdesk_id", sa.String(length=32), nullable=True),
        sa.Column("permanent_password", sa.String(length=512), server_default="", nullable=False),
        sa.Column("password_rotated_at", sa.DateTime(), nullable=True),
        sa.Column("desired_hidden", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("desired_block_outgoing", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("desired_unattended", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("managed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("deploy_state", sa.String(length=16), nullable=False, server_default="unknown"),
        sa.Column("deploy_detail", sa.String(length=512), nullable=True),
        sa.Column("installed_version", sa.String(length=32), nullable=True),
        sa.Column("online", sa.Boolean(), nullable=True),
        sa.Column("logged_in_user", sa.String(length=128), nullable=True),
        sa.Column("last_ip", sa.String(length=64), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("last_deployed_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["computer_id"], ["computer.id"]),
        sa.ForeignKeyConstraint(["media_player_id"], ["mediaplayer.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_remoteaccessdevice_hostname", "remoteaccessdevice", ["hostname"], unique=True)
    op.create_index("ix_remoteaccessdevice_computer_id", "remoteaccessdevice", ["computer_id"])
    op.create_index("ix_remoteaccessdevice_media_player_id", "remoteaccessdevice", ["media_player_id"])
    op.create_index("ix_remoteaccessdevice_location", "remoteaccessdevice", ["location"])
    op.create_index("ix_remoteaccessdevice_rustdesk_id", "remoteaccessdevice", ["rustdesk_id"])
    op.create_index("ix_remoteaccessdevice_managed", "remoteaccessdevice", ["managed"])
    op.create_index("ix_remoteaccessdevice_deploy_state", "remoteaccessdevice", ["deploy_state"])
    op.create_index("ix_remoteaccessdevice_online", "remoteaccessdevice", ["online"])
    op.create_index("ix_remoteaccessdevice_last_seen_at", "remoteaccessdevice", ["last_seen_at"])
    op.create_index("ix_remoteaccessdevice_created_at", "remoteaccessdevice", ["created_at"])

    op.create_table(
        "remoteaccessdeployjob",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("claimed_by", sa.String(length=128), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("result_detail", sa.String(length=2048), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["remoteaccessdevice.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_remoteaccessdeployjob_device_id", "remoteaccessdeployjob", ["device_id"])
    op.create_index("ix_remoteaccessdeployjob_hostname", "remoteaccessdeployjob", ["hostname"])
    op.create_index("ix_remoteaccessdeployjob_action", "remoteaccessdeployjob", ["action"])
    op.create_index("ix_remoteaccessdeployjob_status", "remoteaccessdeployjob", ["status"])
    op.create_index("ix_remoteaccessdeployjob_created_at", "remoteaccessdeployjob", ["created_at"])


def downgrade() -> None:
    op.drop_table("remoteaccessdeployjob")
    op.drop_table("remoteaccessdevice")
