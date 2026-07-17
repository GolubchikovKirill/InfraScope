"""widen_switch_password_columns

Revision ID: 9e8d7c6b5a4f
Revises: 3c4d5e6f7a8b
Create Date: 2026-07-17 00:00:00.000000

Widens ssh_password/enable_password on networkswitch from VARCHAR(255) to
VARCHAR(512) to make room for Fernet-encrypted values (see app/core/crypto.py).
Existing plaintext rows are left as-is; they are read/written transparently
by EncryptedString and get encrypted the next time a switch is saved.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9e8d7c6b5a4f"
down_revision: str | Sequence[str] | None = "3c4d5e6f7a8b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "networkswitch",
        "ssh_password",
        existing_type=sa.VARCHAR(length=255),
        type_=sa.VARCHAR(length=512),
        existing_nullable=False,
    )
    op.alter_column(
        "networkswitch",
        "enable_password",
        existing_type=sa.VARCHAR(length=255),
        type_=sa.VARCHAR(length=512),
        existing_nullable=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "networkswitch",
        "enable_password",
        existing_type=sa.VARCHAR(length=512),
        type_=sa.VARCHAR(length=255),
        existing_nullable=False,
    )
    op.alter_column(
        "networkswitch",
        "ssh_password",
        existing_type=sa.VARCHAR(length=512),
        type_=sa.VARCHAR(length=255),
        existing_nullable=False,
    )
