"""mltonerprediction: forecast band, daily rate and what it was based on

Revision ID: 0b42c231ce74
Revises: 926a321779de
Create Date: 2026-10-28 16:00:00.000000

The toner model now forecasts a range (days_low..days_high) from a per-printer
consumption rate, and says whether that rate came from the printer's own
history or from the fleet prior (basis). The table is rewritten on every
scoring run, so the columns start empty and fill on the next one.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0b42c231ce74"
down_revision: str | Sequence[str] | None = "926a321779de"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("mltonerprediction", sa.Column("days_low", sa.Float(), nullable=True))
    op.add_column("mltonerprediction", sa.Column("days_high", sa.Float(), nullable=True))
    op.add_column("mltonerprediction", sa.Column("daily_rate", sa.Float(), nullable=True))
    op.add_column("mltonerprediction", sa.Column("basis", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("mltonerprediction", "basis")
    op.drop_column("mltonerprediction", "daily_rate")
    op.drop_column("mltonerprediction", "days_high")
    op.drop_column("mltonerprediction", "days_low")
