"""add computer and app setting tables

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-03-07 12:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d6e7f8a9b0c1"
down_revision: str | Sequence[str] | None = "c5d6e7f8a9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "computer",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("location", sa.String(length=128), nullable=True),
        sa.Column("comment", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_computer_hostname"), "computer", ["hostname"], unique=False)
    op.create_index(op.f("ix_computer_location"), "computer", ["location"], unique=False)
    op.create_index(op.f("ix_computer_created_at"), "computer", ["created_at"], unique=False)

    op.create_table(
        "appsetting",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", sa.String(length=4000), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_appsetting_key"), "appsetting", ["key"], unique=True)
    op.create_index(op.f("ix_appsetting_updated_at"), "appsetting", ["updated_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_appsetting_updated_at"), table_name="appsetting")
    op.drop_index(op.f("ix_appsetting_key"), table_name="appsetting")
    op.drop_table("appsetting")

    op.drop_index(op.f("ix_computer_created_at"), table_name="computer")
    op.drop_index(op.f("ix_computer_location"), table_name="computer")
    op.drop_index(op.f("ix_computer_hostname"), table_name="computer")
    op.drop_table("computer")
