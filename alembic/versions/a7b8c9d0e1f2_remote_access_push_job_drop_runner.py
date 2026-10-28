"""remote_access: drop push job runner column

Revision ID: a7b8c9d0e1f2
Revises: 4fdba2992a1e
Create Date: 2026-10-28 21:00:00.000000

A push job used to be claimed by an external Windows runner process, which stamped
its own name here. The backend now runs the push itself over WinRM, so there is no
runner identity to record.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "4fdba2992a1e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("remoteaccesspushjob", "runner")


def downgrade() -> None:
    op.add_column("remoteaccesspushjob", sa.Column("runner", sa.String(length=64), nullable=True))
