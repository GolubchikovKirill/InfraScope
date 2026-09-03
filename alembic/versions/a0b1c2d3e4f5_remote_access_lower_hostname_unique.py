"""remote_access: unique index on lower(hostname), not hostname itself

Revision ID: a0b1c2d3e4f5
Revises: f3a4b5c6d7e8
Create Date: 2026-09-03 15:30:00.000000

Windows hostnames are case-insensitive, but every lookup in this domain used
to compare the raw column - sync_from_console keys off whatever casing the
RustDesk client itself self-reports, and the moment that didn't match
inventory's casing byte-for-byte, it minted a second row for a machine
already tracked under the other casing. Caught live: one console sync pass
produced 22 such duplicates, a cleanup round produced another 28.
service._get_or_create_device, seed_from_inventory and _link_inventory are
already fixed to match on lower(hostname) - this closes the same gap at the
database level, since the old plain unique index on `hostname` never stopped
a case-differing duplicate from being inserted in the first place.

Assumes no case-duplicate hostnames exist at migration time (true as of this
writing - both incidents above were manually cleaned up) - the CREATE UNIQUE
INDEX below fails loudly if that ever stops being true, which is the right
failure mode: better a blocked deploy than a silently-still-broken invariant.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a0b1c2d3e4f5"
down_revision: str | Sequence[str] | None = "f3a4b5c6d7e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_remoteaccessdevice_hostname", table_name="remoteaccessdevice")
    op.execute(
        "CREATE UNIQUE INDEX ix_remoteaccessdevice_hostname_lower "
        "ON remoteaccessdevice (lower(hostname))"
    )


def downgrade() -> None:
    op.drop_index("ix_remoteaccessdevice_hostname_lower", table_name="remoteaccessdevice")
    op.create_index(
        "ix_remoteaccessdevice_hostname", "remoteaccessdevice", ["hostname"], unique=True
    )
