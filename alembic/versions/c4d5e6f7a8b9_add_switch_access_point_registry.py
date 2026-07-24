"""add_switch_access_point_registry

Revision ID: c4d5e6f7a8b9
Revises: 4d5e6f7a8b9c
Create Date: 2026-07-24 00:00:00.000000

Adds a persistent registry of APs ever seen on a switch's ap_vlan via CDP,
so the auto-reboot cycle can also detect and act on an AP that has since
gone quiet (invisible to a live CDP scan) instead of only ever reaching
APs healthy enough to still announce themselves. See
app/domains/inventory/ap_auto_reboot.py.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: str | Sequence[str] | None = "4d5e6f7a8b9c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "switchaccesspoint",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("switch_id", sa.Uuid(), nullable=False),
        sa.Column("mac_address", sa.String(length=17), nullable=False),
        sa.Column("port", sa.String(length=64), nullable=False),
        sa.Column("cdp_name", sa.String(length=255), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("exclude_from_auto_reboot", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["switch_id"], ["networkswitch.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_switchaccesspoint_switch_id"), "switchaccesspoint", ["switch_id"])
    op.create_index(op.f("ix_switchaccesspoint_mac_address"), "switchaccesspoint", ["mac_address"])
    op.create_unique_constraint(
        "uq_switchaccesspoint_switch_mac", "switchaccesspoint", ["switch_id", "mac_address"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_switchaccesspoint_switch_mac", "switchaccesspoint", type_="unique")
    op.drop_index(op.f("ix_switchaccesspoint_mac_address"), table_name="switchaccesspoint")
    op.drop_index(op.f("ix_switchaccesspoint_switch_id"), table_name="switchaccesspoint")
    op.drop_table("switchaccesspoint")
