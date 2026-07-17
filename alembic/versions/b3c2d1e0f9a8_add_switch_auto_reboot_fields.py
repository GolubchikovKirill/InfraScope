"""add_switch_auto_reboot_fields

Revision ID: b3c2d1e0f9a8
Revises: 9e8d7c6b5a4f
Create Date: 2026-07-17 00:00:00.000000

Adds opt-in fields for scheduled Wi-Fi AP reboot (VLAN 20 only), gated
per-switch. See app/domains/inventory/ap_auto_reboot.py.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3c2d1e0f9a8"
down_revision: str | Sequence[str] | None = "9e8d7c6b5a4f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "networkswitch",
        sa.Column("auto_reboot_aps_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "networkswitch",
        sa.Column("auto_reboot_mode", sa.String(length=10), nullable=False, server_default="dry_run"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("networkswitch", "auto_reboot_mode")
    op.drop_column("networkswitch", "auto_reboot_aps_enabled")
