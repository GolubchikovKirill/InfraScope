"""add_honest_sign_status_record

Revision ID: 55ec5e4f8b9d
Revises: a7b8c9d0e1f2
Create Date: 2026-10-29 00:00:00.000000

Last Local Module status per Honest Sign register, written by the scheduled
check (tasks.honest_sign_check_cycle). See app/services/honest_sign.py.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "55ec5e4f8b9d"
down_revision: str | Sequence[str] | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "honestsignstatusrecord",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("original_host", sa.String(length=45), nullable=False),
        sa.Column("host", sa.String(length=45), nullable=False),
        sa.Column("reachable", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=True),
        sa.Column("ready", sa.Boolean(), nullable=False),
        sa.Column("message", sa.String(length=255), nullable=False),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
        sa.Column("state_since", sa.DateTime(), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("problem_reported", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_honestsignstatusrecord_original_host"),
        "honestsignstatusrecord",
        ["original_host"],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_honestsignstatusrecord_original_host"), table_name="honestsignstatusrecord")
    op.drop_table("honestsignstatusrecord")
