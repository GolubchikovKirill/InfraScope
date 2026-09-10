"""credentials vault: stored infrastructure logins + password generator backing table

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
Create Date: 2026-09-10 12:00:00.000000

One flat `credential` table behind the superuser-only "Пароли" tab. `secret` and
`notes` are written through app.core.crypto.EncryptedString, so at the DB level
they are just strings (ciphertext when CREDENTIALS_ENCRYPTION_KEYS is set,
plaintext otherwise - same behaviour as the existing switch SSH password
columns). Everything else is plaintext and indexed for search/filter.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: str | Sequence[str] | None = "a0b1c2d3e4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "credential",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False, server_default="other"),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("secret", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("host", sa.String(length=255), nullable=True),
        sa.Column("location", sa.String(length=128), nullable=True),
        sa.Column("url", sa.String(length=512), nullable=True),
        sa.Column("notes", sa.String(length=4096), nullable=True),
        sa.Column("tags", sa.String(length=512), nullable=True),
        sa.Column("secret_rotated_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_credential_title", "credential", ["title"])
    op.create_index("ix_credential_category", "credential", ["category"])
    op.create_index("ix_credential_host", "credential", ["host"])
    op.create_index("ix_credential_location", "credential", ["location"])
    op.create_index("ix_credential_created_by_id", "credential", ["created_by_id"])
    op.create_index("ix_credential_created_at", "credential", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_credential_created_at", table_name="credential")
    op.drop_index("ix_credential_created_by_id", table_name="credential")
    op.drop_index("ix_credential_location", table_name="credential")
    op.drop_index("ix_credential_host", table_name="credential")
    op.drop_index("ix_credential_category", table_name="credential")
    op.drop_index("ix_credential_title", table_name="credential")
    op.drop_table("credential")
