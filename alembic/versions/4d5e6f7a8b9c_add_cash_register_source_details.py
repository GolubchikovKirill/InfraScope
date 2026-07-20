"""add cash register source details

Revision ID: 4d5e6f7a8b9c
Revises: 3c4d5e6f7a8b
Create Date: 2026-07-20 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4d5e6f7a8b9c"
down_revision: str | None = "3c4d5e6f7a8b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cashregister", sa.Column("source_order", sa.Integer(), nullable=True))
    op.add_column("cashregister", sa.Column("location_zone", sa.String(length=8), nullable=True))
    op.add_column("cashregister", sa.Column("sber_store_code", sa.String(length=64), nullable=True))
    op.add_column("cashregister", sa.Column("rosenzweig_number", sa.String(length=64), nullable=True))
    op.add_column("cashregister", sa.Column("second_screen", sa.String(length=64), nullable=True))
    op.add_column("cashregister", sa.Column("piot_status", sa.String(length=128), nullable=True))
    op.add_column("cashregister", sa.Column("cash_drawer", sa.String(length=512), nullable=True))
    op.add_column("cashregister", sa.Column("terminal_status", sa.String(length=128), nullable=True))
    op.create_index(op.f("ix_cashregister_source_order"), "cashregister", ["source_order"], unique=False)
    op.create_index(op.f("ix_cashregister_location_zone"), "cashregister", ["location_zone"], unique=False)
    op.create_index(op.f("ix_cashregister_sber_store_code"), "cashregister", ["sber_store_code"], unique=False)
    op.create_index(op.f("ix_cashregister_rosenzweig_number"), "cashregister", ["rosenzweig_number"], unique=False)
    op.create_index(op.f("ix_cashregister_piot_status"), "cashregister", ["piot_status"], unique=False)
    op.create_index(op.f("ix_cashregister_terminal_status"), "cashregister", ["terminal_status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_cashregister_terminal_status"), table_name="cashregister")
    op.drop_index(op.f("ix_cashregister_piot_status"), table_name="cashregister")
    op.drop_index(op.f("ix_cashregister_rosenzweig_number"), table_name="cashregister")
    op.drop_index(op.f("ix_cashregister_sber_store_code"), table_name="cashregister")
    op.drop_index(op.f("ix_cashregister_location_zone"), table_name="cashregister")
    op.drop_index(op.f("ix_cashregister_source_order"), table_name="cashregister")
    op.drop_column("cashregister", "terminal_status")
    op.drop_column("cashregister", "cash_drawer")
    op.drop_column("cashregister", "piot_status")
    op.drop_column("cashregister", "second_screen")
    op.drop_column("cashregister", "rosenzweig_number")
    op.drop_column("cashregister", "sber_store_code")
    op.drop_column("cashregister", "location_zone")
    op.drop_column("cashregister", "source_order")
