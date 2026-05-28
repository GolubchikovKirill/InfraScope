"""add media client heartbeat

Revision ID: 1a2b3c4d5e6f
Revises: 0f1e2d3c4b5a
Create Date: 2026-05-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision: str = "1a2b3c4d5e6f"
down_revision: str | None = "0f1e2d3c4b5a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mediaclientheartbeat",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("agent_version", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
        sa.Column("hostname", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column("current_revision", sa.Integer(), nullable=True),
        sa.Column("player_state", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("error_message", sqlmodel.sql.sqltypes.AutoString(length=1024), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_mediaclientheartbeat_created_at"), "mediaclientheartbeat", ["created_at"], unique=False)
    op.create_index(
        op.f("ix_mediaclientheartbeat_last_seen_at"), "mediaclientheartbeat", ["last_seen_at"], unique=False
    )
    op.create_index(
        op.f("ix_mediaclientheartbeat_player_id"), "mediaclientheartbeat", ["player_id"], unique=True
    )
    op.create_index(
        op.f("ix_mediaclientheartbeat_player_state"), "mediaclientheartbeat", ["player_state"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_mediaclientheartbeat_player_state"), table_name="mediaclientheartbeat")
    op.drop_index(op.f("ix_mediaclientheartbeat_player_id"), table_name="mediaclientheartbeat")
    op.drop_index(op.f("ix_mediaclientheartbeat_last_seen_at"), table_name="mediaclientheartbeat")
    op.drop_index(op.f("ix_mediaclientheartbeat_created_at"), table_name="mediaclientheartbeat")
    op.drop_table("mediaclientheartbeat")
