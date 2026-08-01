"""add_ap_needs_attention_tracking

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-08-01 13:45:00.000000

Tracks consecutive reboot-recovery failures / no-PoE skips per access point
so a chronically unresponsive AP gets auto-excluded and flagged instead of
being silently retried (or silently skipped) every cycle forever. See
app/domains/inventory/ap_auto_reboot.py and ap_registry.py.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5c6d7e8f9a0"
down_revision: str | Sequence[str] | None = "a4b5c6d7e8f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "switchaccesspoint",
        sa.Column("consecutive_reboot_failures", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "switchaccesspoint",
        sa.Column("consecutive_no_power_skips", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("switchaccesspoint", sa.Column("needs_attention_since", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("switchaccesspoint", "needs_attention_since")
    op.drop_column("switchaccesspoint", "consecutive_no_power_skips")
    op.drop_column("switchaccesspoint", "consecutive_reboot_failures")
