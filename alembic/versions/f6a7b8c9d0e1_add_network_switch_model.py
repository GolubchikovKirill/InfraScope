"""Add NetworkSwitch model

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-02-23
"""

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "networkswitch",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("ip_address", sqlmodel.sql.sqltypes.AutoString(length=45), nullable=False),
        sa.Column("ssh_username", sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False),
        sa.Column("ssh_password", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("enable_password", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("ssh_port", sa.Integer(), nullable=False),
        sa.Column("ap_vlan", sa.Integer(), nullable=False),
        sa.Column("model_info", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column("ios_version", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column("hostname", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column("uptime", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column("is_online", sa.Boolean(), nullable=True),
        sa.Column("last_polled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_networkswitch_ip_address"), "networkswitch", ["ip_address"], unique=True)
    op.create_index(op.f("ix_networkswitch_name"), "networkswitch", ["name"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_networkswitch_name"), table_name="networkswitch")
    op.drop_index(op.f("ix_networkswitch_ip_address"), table_name="networkswitch")
    op.drop_table("networkswitch")
