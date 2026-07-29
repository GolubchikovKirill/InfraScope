"""add_printer_toner_updated_at

Revision ID: a4b5c6d7e8f9
Revises: 9c217a15f80b
Create Date: 2026-07-29 09:00:00.000000

Tracks when toner_black/cyan/magenta/yellow were last actually refreshed by a
full SNMP poll, separate from last_polled_at (which updates on every poll,
including ones that only confirm the printer is offline and leave the stale
toner values untouched). See app/domains/inventory/printer_polling.py.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4b5c6d7e8f9"
down_revision: str | Sequence[str] | None = "9c217a15f80b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("printer", sa.Column("toner_updated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("printer", "toner_updated_at")
