"""add printer_type column

Revision ID: a1b2c3d4e5f6
Revises: cfddc39e63ff
Create Date: 2026-02-23 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "cfddc39e63ff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("printer", sa.Column("printer_type", sa.String(length=20), nullable=False, server_default="laser"))
    op.create_index(op.f("ix_printer_printer_type"), "printer", ["printer_type"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_printer_printer_type"), table_name="printer")
    op.drop_column("printer", "printer_type")
