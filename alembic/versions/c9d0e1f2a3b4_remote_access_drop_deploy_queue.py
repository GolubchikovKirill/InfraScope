"""remote_access: drop the deploy job queue (rollout moves to Kaspersky Security Center)

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-09-02 20:00:00.000000

InfraScope no longer pushes the RustDesk client - the preconfigured package is
rolled out through KSC (docs/rustdesk-ksc-deployment.md). This removes the
Windows deploy agent's queue and the agent-only device columns, and adds
`in_address_book` for the console address-book push InfraScope now owns.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: str | Sequence[str] | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "remoteaccessdevice",
        sa.Column("in_address_book", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_remoteaccessdevice_in_address_book", "remoteaccessdevice", ["in_address_book"])

    for col in ("deploy_state", "deploy_detail", "last_deployed_at", "last_error", "password_confirmed_at"):
        op.drop_column("remoteaccessdevice", col)

    op.drop_table("remoteaccessdeployjob")


def downgrade() -> None:
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

    op.add_column("remoteaccessdevice", sa.Column("password_confirmed_at", sa.DateTime(), nullable=True))
    op.add_column("remoteaccessdevice", sa.Column("last_error", sa.String(length=1024), nullable=True))
    op.add_column("remoteaccessdevice", sa.Column("last_deployed_at", sa.DateTime(), nullable=True))
    op.add_column("remoteaccessdevice", sa.Column("deploy_detail", sa.String(length=512), nullable=True))
    op.add_column(
        "remoteaccessdevice",
        sa.Column("deploy_state", sa.String(length=16), nullable=False, server_default="unknown"),
    )
    op.drop_index("ix_remoteaccessdevice_in_address_book", table_name="remoteaccessdevice")
    op.drop_column("remoteaccessdevice", "in_address_book")
