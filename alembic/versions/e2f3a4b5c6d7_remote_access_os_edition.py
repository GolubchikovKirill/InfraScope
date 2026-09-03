"""remote_access: self-reported Windows edition + AppLocker support

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-09-03 12:00:00.000000

`desired_block_outgoing` relies on AppLocker, which Windows Home does not
support - the endpoint script silently skips that step there, and until now
InfraScope had no way to tell the operator it happened. The rollout script
already runs as SYSTEM on the endpoint, so it self-reports its own registry
`EditionID` (locale-independent: "Professional", "Enterprise", "Core" for
Home, ...) on every deploy report; the backend classifies it into
`applocker_supported` so the UI can flag machines where the lockdown the
operator asked for silently did not apply.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: str | Sequence[str] | None = "d1e2f3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "remoteaccessdevice", sa.Column("os_edition", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "remoteaccessdevice", sa.Column("os_caption", sa.String(length=128), nullable=True)
    )
    op.add_column(
        "remoteaccessdevice", sa.Column("applocker_supported", sa.Boolean(), nullable=True)
    )
    op.create_index(
        "ix_remoteaccessdevice_applocker_supported",
        "remoteaccessdevice",
        ["applocker_supported"],
    )


def downgrade() -> None:
    op.drop_index("ix_remoteaccessdevice_applocker_supported", table_name="remoteaccessdevice")
    op.drop_column("remoteaccessdevice", "applocker_supported")
    op.drop_column("remoteaccessdevice", "os_caption")
    op.drop_column("remoteaccessdevice", "os_edition")
