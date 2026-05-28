"""add cartridge stock tables

Revision ID: 3c4d5e6f7a8b
Revises: 2b3c4d5e6f7a
Create Date: 2026-05-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision: str = "3c4d5e6f7a8b"
down_revision: str | None = "2b3c4d5e6f7a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cartridgestock",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("cartridge_name", sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False),
        sa.Column("toner_color", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=True),
        sa.Column("compatible_printer_models", sqlmodel.sql.sqltypes.AutoString(length=1024), nullable=False),
        sa.Column("printer_count", sa.Integer(), nullable=False),
        sa.Column("quantity_on_hand", sa.Integer(), nullable=False),
        sa.Column("minimum_stock", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_cartridgestock_cartridge_name"), "cartridgestock", ["cartridge_name"], unique=True)
    op.create_index(op.f("ix_cartridgestock_created_at"), "cartridgestock", ["created_at"], unique=False)
    op.create_index(op.f("ix_cartridgestock_is_active"), "cartridgestock", ["is_active"], unique=False)
    op.create_index(op.f("ix_cartridgestock_last_synced_at"), "cartridgestock", ["last_synced_at"], unique=False)
    op.create_index(op.f("ix_cartridgestock_quantity_on_hand"), "cartridgestock", ["quantity_on_hand"], unique=False)
    op.create_index(op.f("ix_cartridgestock_toner_color"), "cartridgestock", ["toner_color"], unique=False)

    op.create_table(
        "cartridgestockmovement",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("stock_id", sa.Uuid(), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("reason", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("note", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=True),
        sa.Column("created_by", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["stock_id"], ["cartridgestock.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_cartridgestockmovement_created_at"), "cartridgestockmovement", ["created_at"], unique=False
    )
    op.create_index(op.f("ix_cartridgestockmovement_reason"), "cartridgestockmovement", ["reason"], unique=False)
    op.create_index(op.f("ix_cartridgestockmovement_stock_id"), "cartridgestockmovement", ["stock_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_cartridgestockmovement_stock_id"), table_name="cartridgestockmovement")
    op.drop_index(op.f("ix_cartridgestockmovement_reason"), table_name="cartridgestockmovement")
    op.drop_index(op.f("ix_cartridgestockmovement_created_at"), table_name="cartridgestockmovement")
    op.drop_table("cartridgestockmovement")
    op.drop_index(op.f("ix_cartridgestock_toner_color"), table_name="cartridgestock")
    op.drop_index(op.f("ix_cartridgestock_quantity_on_hand"), table_name="cartridgestock")
    op.drop_index(op.f("ix_cartridgestock_last_synced_at"), table_name="cartridgestock")
    op.drop_index(op.f("ix_cartridgestock_is_active"), table_name="cartridgestock")
    op.drop_index(op.f("ix_cartridgestock_created_at"), table_name="cartridgestock")
    op.drop_index(op.f("ix_cartridgestock_cartridge_name"), table_name="cartridgestock")
    op.drop_table("cartridgestock")
