"""add_switch_port_snapshot

Revision ID: 2dd0959f41cb
Revises: d5e6f7a8b9c0
Create Date: 2026-07-25 00:00:00.000000

Adds a history table of switch port-config snapshots, written by a periodic
background task only when the config actually changed since the last stored
row. See app/domains/inventory/port_snapshot.py.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2dd0959f41cb"
down_revision: str | Sequence[str] | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "switchportsnapshot",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("switch_id", sa.Uuid(), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("ports_hash", sa.String(length=64), nullable=False),
        sa.Column("ports_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["switch_id"], ["networkswitch.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_switchportsnapshot_switch_id"), "switchportsnapshot", ["switch_id"])
    op.create_index(op.f("ix_switchportsnapshot_captured_at"), "switchportsnapshot", ["captured_at"])
    op.create_index(op.f("ix_switchportsnapshot_ports_hash"), "switchportsnapshot", ["ports_hash"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_switchportsnapshot_ports_hash"), table_name="switchportsnapshot")
    op.drop_index(op.f("ix_switchportsnapshot_captured_at"), table_name="switchportsnapshot")
    op.drop_index(op.f("ix_switchportsnapshot_switch_id"), table_name="switchportsnapshot")
    op.drop_table("switchportsnapshot")
