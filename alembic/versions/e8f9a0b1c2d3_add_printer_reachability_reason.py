"""add_printer_reachability_reason

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-08-13 08:00:00.000000

Same convention as NetworkSwitch/Computer/CashRegister.reachability_reason
(see d7e8f9a0b1c2). Printers only get a coarse reason ("no_response",
"target_invalid", "poll_error") since SNMP over UDP can't distinguish a
wrong community string from a dead route the way SSH can - both just time
out. The subnet-wide path-failure heuristic (printer_polling.
_subnets_with_total_failure) is what actually catches the network-vs-device
distinction here, by leaving affected printers' state untouched entirely
rather than guessing.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e8f9a0b1c2d3"
down_revision: str | Sequence[str] | None = "d7e8f9a0b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("printer", sa.Column("reachability_reason", sa.String(length=64), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("printer", "reachability_reason")
