"""add_switch_dhcp_clear_fields

Revision ID: d8e9f0a1b2c3
Revises: c1d2e3f4a5b6
Create Date: 2026-10-28 00:00:00.000000

Adds opt-in fields for scheduled DHCP cleanup, gated per switch. See
app/domains/inventory/dhcp_clear.py.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8e9f0a1b2c3"
down_revision: str | Sequence[str] | None = "c1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "networkswitch",
        sa.Column("dhcp_clear_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "networkswitch",
        sa.Column("dhcp_clear_mode", sa.String(length=10), nullable=False, server_default="dry_run"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("networkswitch", "dhcp_clear_mode")
    op.drop_column("networkswitch", "dhcp_clear_enabled")
