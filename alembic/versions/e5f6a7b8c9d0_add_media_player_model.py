"""add media_player model

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-02-23 22:01:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mediaplayer",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_type", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=False),
        sa.Column("mac_address", sa.String(length=17), nullable=True),
        sa.Column("is_online", sa.Boolean(), nullable=True),
        sa.Column("hostname", sa.String(length=255), nullable=True),
        sa.Column("os_info", sa.String(length=255), nullable=True),
        sa.Column("uptime", sa.String(length=100), nullable=True),
        sa.Column("open_ports", sa.String(length=500), nullable=True),
        sa.Column("last_polled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ip_address"),
    )
    op.create_index(op.f("ix_mediaplayer_device_type"), "mediaplayer", ["device_type"])
    op.create_index(op.f("ix_mediaplayer_ip_address"), "mediaplayer", ["ip_address"])
    op.create_index(op.f("ix_mediaplayer_name"), "mediaplayer", ["name"])


def downgrade() -> None:
    op.drop_index(op.f("ix_mediaplayer_name"), table_name="mediaplayer")
    op.drop_index(op.f("ix_mediaplayer_ip_address"), table_name="mediaplayer")
    op.drop_index(op.f("ix_mediaplayer_device_type"), table_name="mediaplayer")
    op.drop_table("mediaplayer")
