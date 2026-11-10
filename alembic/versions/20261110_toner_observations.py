"""Track the actual measurement time of each cartridge."""

import sqlalchemy as sa

from alembic import op

revision = "20261110_toner"
down_revision = "55ec5e4f8b9d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Historical aggregate timestamps cannot prove per-color freshness.
    op.add_column("printer", sa.Column("toner_observed_at", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_column("printer", "toner_observed_at")
