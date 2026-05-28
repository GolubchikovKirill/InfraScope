"""add toner cartridge names to printer

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-02-23 23:58:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2a3b4c5d6e7"
down_revision: str | Sequence[str] | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("printer", sa.Column("toner_black_name", sa.String(length=128), nullable=True))
    op.add_column("printer", sa.Column("toner_cyan_name", sa.String(length=128), nullable=True))
    op.add_column("printer", sa.Column("toner_magenta_name", sa.String(length=128), nullable=True))
    op.add_column("printer", sa.Column("toner_yellow_name", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("printer", "toner_yellow_name")
    op.drop_column("printer", "toner_magenta_name")
    op.drop_column("printer", "toner_cyan_name")
    op.drop_column("printer", "toner_black_name")
