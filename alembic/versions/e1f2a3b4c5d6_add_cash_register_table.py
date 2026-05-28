"""add cash register table

Revision ID: e1f2a3b4c5d6
Revises: d9e0f1a2b3c4
Create Date: 2026-02-23 23:35:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: str | Sequence[str] | None = "d9e0f1a2b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cashregister",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kkm_number", sa.String(length=64), nullable=False),
        sa.Column("store_code", sa.String(length=64), nullable=True),
        sa.Column("serial_number", sa.String(length=128), nullable=True),
        sa.Column("inventory_number", sa.String(length=128), nullable=True),
        sa.Column("terminal_id_rs", sa.String(length=128), nullable=True),
        sa.Column("terminal_id_sber", sa.String(length=128), nullable=True),
        sa.Column("windows_version", sa.String(length=128), nullable=True),
        sa.Column("kkm_type", sa.String(length=16), nullable=False),
        sa.Column("cash_number", sa.String(length=64), nullable=True),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("comment", sa.String(length=1024), nullable=True),
        sa.Column("is_online", sa.Boolean(), nullable=True),
        sa.Column("reachability_reason", sa.String(length=64), nullable=True),
        sa.Column("last_polled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_cashregister_cash_number"), "cashregister", ["cash_number"], unique=False)
    op.create_index(op.f("ix_cashregister_created_at"), "cashregister", ["created_at"], unique=False)
    op.create_index(op.f("ix_cashregister_hostname"), "cashregister", ["hostname"], unique=False)
    op.create_index(op.f("ix_cashregister_inventory_number"), "cashregister", ["inventory_number"], unique=False)
    op.create_index(op.f("ix_cashregister_is_online"), "cashregister", ["is_online"], unique=False)
    op.create_index(op.f("ix_cashregister_kkm_number"), "cashregister", ["kkm_number"], unique=False)
    op.create_index(op.f("ix_cashregister_kkm_type"), "cashregister", ["kkm_type"], unique=False)
    op.create_index(op.f("ix_cashregister_last_polled_at"), "cashregister", ["last_polled_at"], unique=False)
    op.create_index(op.f("ix_cashregister_serial_number"), "cashregister", ["serial_number"], unique=False)
    op.create_index(op.f("ix_cashregister_store_code"), "cashregister", ["store_code"], unique=False)
    op.create_index(op.f("ix_cashregister_terminal_id_rs"), "cashregister", ["terminal_id_rs"], unique=False)
    op.create_index(op.f("ix_cashregister_terminal_id_sber"), "cashregister", ["terminal_id_sber"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_cashregister_terminal_id_sber"), table_name="cashregister")
    op.drop_index(op.f("ix_cashregister_terminal_id_rs"), table_name="cashregister")
    op.drop_index(op.f("ix_cashregister_store_code"), table_name="cashregister")
    op.drop_index(op.f("ix_cashregister_serial_number"), table_name="cashregister")
    op.drop_index(op.f("ix_cashregister_last_polled_at"), table_name="cashregister")
    op.drop_index(op.f("ix_cashregister_kkm_type"), table_name="cashregister")
    op.drop_index(op.f("ix_cashregister_kkm_number"), table_name="cashregister")
    op.drop_index(op.f("ix_cashregister_is_online"), table_name="cashregister")
    op.drop_index(op.f("ix_cashregister_inventory_number"), table_name="cashregister")
    op.drop_index(op.f("ix_cashregister_hostname"), table_name="cashregister")
    op.drop_index(op.f("ix_cashregister_created_at"), table_name="cashregister")
    op.drop_index(op.f("ix_cashregister_cash_number"), table_name="cashregister")
    op.drop_table("cashregister")
