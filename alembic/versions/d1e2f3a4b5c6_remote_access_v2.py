"""remote_access v2: console accounts, shared address book, reported rollout state

Revision ID: d1e2f3a4b5c6
Revises: c9d0e1f2a3b4
Create Date: 2026-09-02 22:10:00.000000

Adds what InfraScope needs to own the RustDesk fleet end to end:

* `remoteaccessconsoleaccount` - the console logins InfraScope provisions for
  engineers. No password column on purpose: the secret is shown once at creation
  and can only be reset, never read back.
* device columns for the shared address book (`ab_row_id`, `ab_password_pushed`)
  so a push updates the existing console row instead of piling up duplicates.
* device columns for the rollout state the endpoint script reports back
  (`deploy_state` and friends). This is the same shape the old deploy queue had,
  but it is now *reported* by the machine rather than *inferred* by a job runner.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: str | Sequence[str] | None = "c9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("remoteaccessdevice", sa.Column("ab_row_id", sa.Integer(), nullable=True))
    op.add_column(
        "remoteaccessdevice",
        sa.Column("ab_password_pushed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "remoteaccessdevice",
        sa.Column(
            "deploy_state",
            sa.String(length=16),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column(
        "remoteaccessdevice",
        sa.Column("deploy_detail", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "remoteaccessdevice", sa.Column("deploy_requested_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "remoteaccessdevice", sa.Column("deploy_reported_at", sa.DateTime(), nullable=True)
    )
    op.create_index(
        "ix_remoteaccessdevice_deploy_state", "remoteaccessdevice", ["deploy_state"]
    )

    op.create_table(
        "remoteaccessconsoleaccount",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("console_user_id", sa.Integer(), nullable=True),
        sa.Column("display_name", sa.String(length=128), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("infrascope_user_id", sa.Uuid(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("book_shared", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["infrascope_user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_remoteaccessconsoleaccount_username",
        "remoteaccessconsoleaccount",
        ["username"],
        unique=True,
    )
    op.create_index(
        "ix_remoteaccessconsoleaccount_console_user_id",
        "remoteaccessconsoleaccount",
        ["console_user_id"],
    )
    op.create_index(
        "ix_remoteaccessconsoleaccount_infrascope_user_id",
        "remoteaccessconsoleaccount",
        ["infrascope_user_id"],
    )
    op.create_index(
        "ix_remoteaccessconsoleaccount_active", "remoteaccessconsoleaccount", ["active"]
    )
    op.create_index(
        "ix_remoteaccessconsoleaccount_created_at", "remoteaccessconsoleaccount", ["created_at"]
    )


def downgrade() -> None:
    for name in (
        "ix_remoteaccessconsoleaccount_created_at",
        "ix_remoteaccessconsoleaccount_active",
        "ix_remoteaccessconsoleaccount_infrascope_user_id",
        "ix_remoteaccessconsoleaccount_console_user_id",
        "ix_remoteaccessconsoleaccount_username",
    ):
        op.drop_index(name, table_name="remoteaccessconsoleaccount")
    op.drop_table("remoteaccessconsoleaccount")

    op.drop_index("ix_remoteaccessdevice_deploy_state", table_name="remoteaccessdevice")
    for col in (
        "deploy_reported_at",
        "deploy_requested_at",
        "deploy_detail",
        "deploy_state",
        "ab_password_pushed",
        "ab_row_id",
    ):
        op.drop_column("remoteaccessdevice", col)
