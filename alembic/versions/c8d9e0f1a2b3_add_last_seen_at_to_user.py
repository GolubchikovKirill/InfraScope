"""Add last_seen_at to user

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-02-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c8d9e0f1a2b3"
down_revision: str | Sequence[str] | None = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user", sa.Column("last_seen_at", sa.DateTime(), nullable=True))
    op.create_index(op.f("ix_user_last_seen_at"), "user", ["last_seen_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_user_last_seen_at"), table_name="user")
    op.drop_column("user", "last_seen_at")
