"""add_media_center_tables

Revision ID: 0f1e2d3c4b5a
Revises: fba776f80d0f
Create Date: 2026-05-22 09:35:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0f1e2d3c4b5a"
down_revision: str | Sequence[str] | None = "fba776f80d0f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mediaasset",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=32), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_mediaasset_created_at"), "mediaasset", ["created_at"], unique=False)
    op.create_index(op.f("ix_mediaasset_is_active"), "mediaasset", ["is_active"], unique=False)
    op.create_index(op.f("ix_mediaasset_media_type"), "mediaasset", ["media_type"], unique=False)
    op.create_index(op.f("ix_mediaasset_title"), "mediaasset", ["title"], unique=False)

    op.create_table(
        "mediaassignment",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=32), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("playback_mode", sa.String(length=32), nullable=False),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_mediaassignment_asset_id"), "mediaassignment", ["asset_id"], unique=False)
    op.create_index(op.f("ix_mediaassignment_created_at"), "mediaassignment", ["created_at"], unique=False)
    op.create_index(op.f("ix_mediaassignment_enabled"), "mediaassignment", ["enabled"], unique=False)
    op.create_index(op.f("ix_mediaassignment_player_id"), "mediaassignment", ["player_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_mediaassignment_player_id"), table_name="mediaassignment")
    op.drop_index(op.f("ix_mediaassignment_enabled"), table_name="mediaassignment")
    op.drop_index(op.f("ix_mediaassignment_created_at"), table_name="mediaassignment")
    op.drop_index(op.f("ix_mediaassignment_asset_id"), table_name="mediaassignment")
    op.drop_table("mediaassignment")
    op.drop_index(op.f("ix_mediaasset_title"), table_name="mediaasset")
    op.drop_index(op.f("ix_mediaasset_media_type"), table_name="mediaasset")
    op.drop_index(op.f("ix_mediaasset_is_active"), table_name="mediaasset")
    op.drop_index(op.f("ix_mediaasset_created_at"), table_name="mediaasset")
    op.drop_table("mediaasset")
