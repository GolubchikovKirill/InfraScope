"""add computer polling fields

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-03-07 12:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7f8a9b0c1d2"
down_revision: str | Sequence[str] | None = "d6e7f8a9b0c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("computer", sa.Column("is_online", sa.Boolean(), nullable=True))
    op.add_column("computer", sa.Column("reachability_reason", sa.String(length=64), nullable=True))
    op.add_column("computer", sa.Column("last_polled_at", sa.DateTime(), nullable=True))
    op.create_index(op.f("ix_computer_is_online"), "computer", ["is_online"], unique=False)
    op.create_index(op.f("ix_computer_last_polled_at"), "computer", ["last_polled_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_computer_last_polled_at"), table_name="computer")
    op.drop_index(op.f("ix_computer_is_online"), table_name="computer")
    op.drop_column("computer", "last_polled_at")
    op.drop_column("computer", "reachability_reason")
    op.drop_column("computer", "is_online")
