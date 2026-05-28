"""add store number to cash register

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-03-07 10:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4c5d6e7f8a9"
down_revision: str | Sequence[str] | None = "a3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cashregister", sa.Column("store_number", sa.String(length=64), nullable=True))
    op.create_index(op.f("ix_cashregister_store_number"), "cashregister", ["store_number"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_cashregister_store_number"), table_name="cashregister")
    op.drop_column("cashregister", "store_number")
