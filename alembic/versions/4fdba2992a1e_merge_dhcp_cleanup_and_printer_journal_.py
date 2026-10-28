"""merge dhcp cleanup and printer journal heads

Revision ID: 4fdba2992a1e
Revises: 17bf293d0ea5, d8e9f0a1b2c3
Create Date: 2026-10-28 19:46:38.874218

The DHCP cleanup migration was written on a branch cut before the event log
index and the printer journal landed, so both chains hang off c1d2e3f4a5b6.
No schema change here, only one head again.
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "4fdba2992a1e"
down_revision: str | Sequence[str] | None = ("17bf293d0ea5", "d8e9f0a1b2c3")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
