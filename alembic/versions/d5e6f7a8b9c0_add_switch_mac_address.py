"""add_switch_mac_address

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-07-24 00:00:00.000000

Adds mac_address/mac_status to networkswitch, mirroring printer/mediaplayer,
so a switch can be rediscovered by MAC if its ip_address ever changes. See
app/services/mac_rediscovery.py and app/services/switch_mac_lookup.py.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5e6f7a8b9c0"
down_revision: str | Sequence[str] | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("networkswitch", sa.Column("mac_address", sa.String(length=17), nullable=True))
    op.add_column("networkswitch", sa.Column("mac_status", sa.String(length=20), nullable=True))
    op.create_index(op.f("ix_networkswitch_mac_address"), "networkswitch", ["mac_address"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_networkswitch_mac_address"), table_name="networkswitch")
    op.drop_column("networkswitch", "mac_status")
    op.drop_column("networkswitch", "mac_address")
