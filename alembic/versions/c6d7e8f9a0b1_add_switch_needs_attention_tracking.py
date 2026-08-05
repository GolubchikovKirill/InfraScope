"""add_switch_needs_attention_tracking

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-08-05 05:00:00.000000

Tracks consecutive scheduled-cycle failures at the switch level (SSH
unreachable, or genuinely zero known APs on ap_vlan) - the AP-level
escalation added in b5c6d7e8f9a0 only covers "found an AP but it's not
healthy"; these two failure modes happen before any AP is even found, so
they need their own streak. See app/domains/inventory/ap_auto_reboot.py.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c6d7e8f9a0b1"
down_revision: str | Sequence[str] | None = "b5c6d7e8f9a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "networkswitch",
        sa.Column("consecutive_unreachable_cycles", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "networkswitch",
        sa.Column("consecutive_no_aps_found_cycles", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("networkswitch", sa.Column("switch_needs_attention_since", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("networkswitch", "switch_needs_attention_since")
    op.drop_column("networkswitch", "consecutive_no_aps_found_cycles")
    op.drop_column("networkswitch", "consecutive_unreachable_cycles")
