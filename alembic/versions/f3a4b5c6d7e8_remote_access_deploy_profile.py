"""remote_access: named client/admin deploy profile

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-09-03 13:00:00.000000

Found live on VNA-MGR-15: an ordinary employee could open RustDesk themselves
and use it to connect out, because that device row had never gone through the
new rollout at all. Fixing that machine surfaced a second gap - the *engineer*
workstation that does the fixing (VNK-ITD-SA05) was seeded with the exact same
"client" lockdown defaults (hidden, AppLocker-blocked, unattended) that make
sense for a store kiosk and are exactly backwards for a machine an engineer
sits at and uses to connect *out*.

`deploy_profile` names the two presets (service.DEPLOY_PROFILES) so bulk
operations and the UI can set all three flags correctly in one action instead
of an operator getting three booleans right by hand every time. All existing
rows default to "client" - the safe choice for the ~150 store endpoints this
fleet is mostly made of.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f3a4b5c6d7e8"
down_revision: str | Sequence[str] | None = "e2f3a4b5c6d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "remoteaccessdevice",
        sa.Column("deploy_profile", sa.String(length=16), nullable=False, server_default="client"),
    )
    op.create_index("ix_remoteaccessdevice_deploy_profile", "remoteaccessdevice", ["deploy_profile"])


def downgrade() -> None:
    op.drop_index("ix_remoteaccessdevice_deploy_profile", table_name="remoteaccessdevice")
    op.drop_column("remoteaccessdevice", "deploy_profile")
