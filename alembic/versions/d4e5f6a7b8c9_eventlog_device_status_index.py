"""eventlog: composite index for per-device status history

Revision ID: d4e5f6a7b8c9
Revises: c1d2e3f4a5b6
Create Date: 2026-10-28 12:00:00.000000

Every printer list response counts each printer's offline events of the last
24 hours (the "unstable link" badge): device_kind + event_type + created_at
range + device_name IN (...). With only single-column indexes Postgres picks
one of them and filters the rest row by row, and the table only grows. One
composite index answers the whole predicate; device_name last so the range on
created_at still narrows the scan first.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | Sequence[str] | None = "c1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_eventlog_kind_type_created"


def upgrade() -> None:
    op.create_index(
        INDEX_NAME,
        "eventlog",
        ["device_kind", "event_type", "created_at", "device_name"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="eventlog")
