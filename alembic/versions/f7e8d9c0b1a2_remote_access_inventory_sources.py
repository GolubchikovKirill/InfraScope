"""remote_access: link cash registers + nettops, tag source_kind

Revision ID: f7e8d9c0b1a2
Revises: f1a2b3c4d5e6
Create Date: 2026-09-02 14:30:00.000000

RemoteAccessDevice previously seeded only from `computer`. It now mirrors the
whole InfraScope endpoint inventory: every cash register, every computer, and
media players of type 'nettop' (iconbit/twix are Android sticks, not Windows).

* cash_register_id - soft FK to `cashregister`, same idea as computer_id
* source_kind      - which table owns the host: cash_register | computer | media_player
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f7e8d9c0b1a2"
down_revision: str | Sequence[str] | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("remoteaccessdevice", sa.Column("cash_register_id", sa.Uuid(), nullable=True))
    op.add_column(
        "remoteaccessdevice",
        sa.Column("source_kind", sa.String(length=16), nullable=False, server_default="computer"),
    )
    op.create_index(
        "ix_remoteaccessdevice_cash_register_id", "remoteaccessdevice", ["cash_register_id"]
    )
    op.create_index("ix_remoteaccessdevice_source_kind", "remoteaccessdevice", ["source_kind"])
    op.create_foreign_key(
        "fk_remoteaccessdevice_cash_register_id_cashregister",
        "remoteaccessdevice",
        "cashregister",
        ["cash_register_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_remoteaccessdevice_cash_register_id_cashregister",
        "remoteaccessdevice",
        type_="foreignkey",
    )
    op.drop_index("ix_remoteaccessdevice_source_kind", table_name="remoteaccessdevice")
    op.drop_index("ix_remoteaccessdevice_cash_register_id", table_name="remoteaccessdevice")
    op.drop_column("remoteaccessdevice", "source_kind")
    op.drop_column("remoteaccessdevice", "cash_register_id")
