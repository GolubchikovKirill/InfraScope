"""add event log table

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-02-23 22:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d9e0f1a2b3c4"
down_revision: str | Sequence[str] | None = "c8d9e0f1a2b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "eventlog",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("message", sa.String(length=1024), nullable=False),
        sa.Column("device_kind", sa.String(length=32), nullable=True),
        sa.Column("device_name", sa.String(length=255), nullable=True),
        sa.Column("ip_address", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_eventlog_category"), "eventlog", ["category"], unique=False)
    op.create_index(op.f("ix_eventlog_created_at"), "eventlog", ["created_at"], unique=False)
    op.create_index(op.f("ix_eventlog_device_kind"), "eventlog", ["device_kind"], unique=False)
    op.create_index(op.f("ix_eventlog_event_type"), "eventlog", ["event_type"], unique=False)
    op.create_index(op.f("ix_eventlog_ip_address"), "eventlog", ["ip_address"], unique=False)
    op.create_index(op.f("ix_eventlog_severity"), "eventlog", ["severity"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_eventlog_severity"), table_name="eventlog")
    op.drop_index(op.f("ix_eventlog_ip_address"), table_name="eventlog")
    op.drop_index(op.f("ix_eventlog_event_type"), table_name="eventlog")
    op.drop_index(op.f("ix_eventlog_device_kind"), table_name="eventlog")
    op.drop_index(op.f("ix_eventlog_created_at"), table_name="eventlog")
    op.drop_index(op.f("ix_eventlog_category"), table_name="eventlog")
    op.drop_table("eventlog")
