"""add netsupport target to cash register

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-03-07 11:15:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5d6e7f8a9b0"
down_revision: str | Sequence[str] | None = "b4c5d6e7f8a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cashregister", sa.Column("netsupport_target", sa.String(length=255), nullable=True))
    op.create_index(op.f("ix_cashregister_netsupport_target"), "cashregister", ["netsupport_target"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_cashregister_netsupport_target"), table_name="cashregister")
    op.drop_column("cashregister", "netsupport_target")
