"""add media asset file fields

Revision ID: 2b3c4d5e6f7a
Revises: 1a2b3c4d5e6f
Create Date: 2026-05-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision: str = "2b3c4d5e6f7a"
down_revision: str | None = "1a2b3c4d5e6f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("mediaasset", sa.Column("original_filename", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True))
    op.add_column("mediaasset", sa.Column("stored_filename", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True))
    op.add_column("mediaasset", sa.Column("content_type", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True))
    op.add_column("mediaasset", sa.Column("file_size_bytes", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_mediaasset_stored_filename"), "mediaasset", ["stored_filename"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_mediaasset_stored_filename"), table_name="mediaasset")
    op.drop_column("mediaasset", "file_size_bytes")
    op.drop_column("mediaasset", "content_type")
    op.drop_column("mediaasset", "stored_filename")
    op.drop_column("mediaasset", "original_filename")
