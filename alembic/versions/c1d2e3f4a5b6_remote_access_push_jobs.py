"""remote_access: queue for pushes run by a Windows runner

Revision ID: c1d2e3f4a5b6
Revises: b1c2d3e4f5a6
Create Date: 2026-09-19 19:00:00.000000

A push job is a request "install/configure RustDesk on this machine over the network".
The server never executes anything on the fleet: a runner on a Windows admin host claims
the jobs and runs the push kit there (docs/rustdesk-deployment.md), then reports back.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: str | Sequence[str] | None = "b1c2d3e4f5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "remoteaccesspushjob",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("profile", sa.String(length=16), nullable=False, server_default="client"),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("detail", sa.String(length=1024), nullable=True),
        sa.Column("requested_by", sa.String(length=255), nullable=True),
        sa.Column("runner", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["remoteaccessdevice.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_remoteaccesspushjob_device_id", "remoteaccesspushjob", ["device_id"])
    op.create_index("ix_remoteaccesspushjob_state", "remoteaccesspushjob", ["state"])
    op.create_index("ix_remoteaccesspushjob_created_at", "remoteaccesspushjob", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_remoteaccesspushjob_created_at", table_name="remoteaccesspushjob")
    op.drop_index("ix_remoteaccesspushjob_state", table_name="remoteaccesspushjob")
    op.drop_index("ix_remoteaccesspushjob_device_id", table_name="remoteaccesspushjob")
    op.drop_table("remoteaccesspushjob")
