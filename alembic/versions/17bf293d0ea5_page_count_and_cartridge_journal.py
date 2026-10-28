"""printers: lifetime page count; cartridge replacement journal

Revision ID: 17bf293d0ea5
Revises: 0b42c231ce74
Create Date: 2026-10-28 18:00:00.000000

- printer.page_count / page_count_updated_at: SNMP prtMarkerLifeCount, read on
  the full (hourly) poll.
- mlfeaturesnapshot.page_count: the same counter in the ML history, so the
  toner forecast can learn pages per cartridge once enough has accumulated.
- cartridgereplacement: swaps detected by polling (a colour's level jumping up
  by a refill's worth), with the outgoing cartridge's lifetime and pages.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "17bf293d0ea5"
down_revision: str | Sequence[str] | None = "0b42c231ce74"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("printer", sa.Column("page_count", sa.Integer(), nullable=True))
    op.add_column("printer", sa.Column("page_count_updated_at", sa.DateTime(), nullable=True))
    op.add_column("mlfeaturesnapshot", sa.Column("page_count", sa.Integer(), nullable=True))
    op.create_table(
        "cartridgereplacement",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("printer_id", sa.Uuid(), nullable=True),
        sa.Column("store_name", sa.String(length=255), nullable=False),
        sa.Column("printer_model", sa.String(length=255), nullable=True),
        sa.Column("toner_color", sa.String(length=16), nullable=False),
        sa.Column("cartridge_name", sa.String(length=128), nullable=True),
        sa.Column("level_before", sa.Integer(), nullable=False),
        sa.Column("level_after", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("previous_replaced_at", sa.DateTime(), nullable=True),
        sa.Column("lifetime_days", sa.Float(), nullable=True),
        sa.Column("pages_printed", sa.Integer(), nullable=True),
        sa.Column("replaced_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["printer_id"], ["printer.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cartridgereplacement_printer_id", "cartridgereplacement", ["printer_id"])
    op.create_index("ix_cartridgereplacement_store_name", "cartridgereplacement", ["store_name"])
    op.create_index("ix_cartridgereplacement_toner_color", "cartridgereplacement", ["toner_color"])
    op.create_index("ix_cartridgereplacement_cartridge_name", "cartridgereplacement", ["cartridge_name"])
    op.create_index("ix_cartridgereplacement_replaced_at", "cartridgereplacement", ["replaced_at"])


def downgrade() -> None:
    op.drop_table("cartridgereplacement")
    op.drop_column("mlfeaturesnapshot", "page_count")
    op.drop_column("printer", "page_count_updated_at")
    op.drop_column("printer", "page_count")
