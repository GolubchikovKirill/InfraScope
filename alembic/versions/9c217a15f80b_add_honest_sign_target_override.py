"""add_honest_sign_target_override

Revision ID: 9c217a15f80b
Revises: 2dd0959f41cb
Create Date: 2026-07-25 00:00:00.000000

Lets an operator redirect a Honest Sign target (configured via
HONEST_SIGN_TARGETS in .env) to a different IP from the app, instead of
editing the server .env for a single cash register IP change. See
app/services/honest_sign.py.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9c217a15f80b"
down_revision: str | Sequence[str] | None = "2dd0959f41cb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "honestsigntargetoverride",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("original_host", sa.String(length=45), nullable=False),
        sa.Column("current_host", sa.String(length=45), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_honestsigntargetoverride_original_host"),
        "honestsigntargetoverride",
        ["original_host"],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_honestsigntargetoverride_original_host"), table_name="honestsigntargetoverride")
    op.drop_table("honestsigntargetoverride")
