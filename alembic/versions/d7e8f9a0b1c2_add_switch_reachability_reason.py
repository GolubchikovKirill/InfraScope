"""add_switch_reachability_reason

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-08-13 06:10:00.000000

A 3-day outage (Aug 10-13) was misdiagnosed for days because every switch
connect failure - a wrong password, a dropped route, a closed port - logged
as "password auth failed". This column stores the actual classification
(see app.services.cisco_ssh._classify_ssh_error) so "the network path to
this device is down" no longer looks identical to "someone changed the
enable password". Same convention as Computer/CashRegister.reachability_reason.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7e8f9a0b1c2"
down_revision: str | Sequence[str] | None = "c6d7e8f9a0b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("networkswitch", sa.Column("reachability_reason", sa.String(length=64), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("networkswitch", "reachability_reason")
