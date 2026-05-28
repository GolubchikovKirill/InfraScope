"""Add vendor/snmp fields to network switches

Revision ID: b7c8d9e0f1a2
Revises: f6a7b8c9d0e1
Create Date: 2026-02-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: str | Sequence[str] | None = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("networkswitch", sa.Column("vendor", sa.String(length=32), nullable=False, server_default="cisco"))
    op.add_column(
        "networkswitch",
        sa.Column("management_protocol", sa.String(length=32), nullable=False, server_default="snmp+ssh"),
    )
    op.add_column("networkswitch", sa.Column("snmp_version", sa.String(length=10), nullable=False, server_default="2c"))
    op.add_column(
        "networkswitch",
        sa.Column("snmp_community_ro", sa.String(length=255), nullable=False, server_default="public"),
    )
    op.add_column("networkswitch", sa.Column("snmp_community_rw", sa.String(length=255), nullable=True))
    op.create_index(op.f("ix_networkswitch_vendor"), "networkswitch", ["vendor"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_networkswitch_vendor"), table_name="networkswitch")
    op.drop_column("networkswitch", "snmp_community_rw")
    op.drop_column("networkswitch", "snmp_community_ro")
    op.drop_column("networkswitch", "snmp_version")
    op.drop_column("networkswitch", "management_protocol")
    op.drop_column("networkswitch", "vendor")
