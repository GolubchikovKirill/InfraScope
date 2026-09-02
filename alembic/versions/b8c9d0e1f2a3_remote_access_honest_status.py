"""remote_access: split host vs RustDesk online, confirmed password, fix stuck rows

Revision ID: b8c9d0e1f2a3
Revises: f7e8d9c0b1a2
Create Date: 2026-09-02 18:00:00.000000

* host_online / host_last_seen_at - InfraScope's own reachability result, kept
  apart from `online` (RustDesk-console truth) so the UI stops passing "host
  pings" off as "RustDesk connected".
* password_confirmed_at - set when an agent verifies the password persisted on
  the box; `password_rotated_at` alone only means InfraScope generated one.
* data fix: devices stuck in deploy_state='installing' with no in-flight job
  (the enqueue-time optimism bug) are reset to 'unknown'.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: str | Sequence[str] | None = "f7e8d9c0b1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("remoteaccessdevice", sa.Column("password_confirmed_at", sa.DateTime(), nullable=True))
    op.add_column("remoteaccessdevice", sa.Column("host_online", sa.Boolean(), nullable=True))
    op.add_column("remoteaccessdevice", sa.Column("host_last_seen_at", sa.DateTime(), nullable=True))
    op.create_index("ix_remoteaccessdevice_host_online", "remoteaccessdevice", ["host_online"])

    op.execute(
        """
        UPDATE remoteaccessdevice
        SET deploy_state = 'unknown'
        WHERE deploy_state = 'installing'
          AND id NOT IN (
              SELECT device_id FROM remoteaccessdeployjob
              WHERE status IN ('queued', 'claimed', 'running')
          )
        """
    )


def downgrade() -> None:
    op.drop_index("ix_remoteaccessdevice_host_online", table_name="remoteaccessdevice")
    op.drop_column("remoteaccessdevice", "host_last_seen_at")
    op.drop_column("remoteaccessdevice", "host_online")
    op.drop_column("remoteaccessdevice", "password_confirmed_at")
