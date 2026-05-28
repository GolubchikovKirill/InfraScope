"""add connection_type and host_pc to printer

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-02-23 22:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | Sequence[str] | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _drop_unique_on_ip(conn):
    """Find and drop any unique constraint or unique index on printer.ip_address."""
    # Try dropping unique constraints by looking them up in pg_constraint
    result = conn.execute(
        sa.text("""
        SELECT con.conname
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
        WHERE rel.relname = 'printer'
          AND con.contype = 'u'
          AND EXISTS (
              SELECT 1 FROM pg_attribute a
              WHERE a.attrelid = rel.oid
                AND a.attnum = ANY(con.conkey)
                AND a.attname = 'ip_address'
          )
    """)
    )
    for row in result:
        conn.execute(sa.text(f'ALTER TABLE printer DROP CONSTRAINT "{row[0]}"'))
        return

    # Fallback: drop unique indexes on ip_address
    result = conn.execute(
        sa.text("""
        SELECT i.relname
        FROM pg_index idx
        JOIN pg_class t ON t.oid = idx.indrelid
        JOIN pg_class i ON i.oid = idx.indexrelid
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(idx.indkey)
        WHERE t.relname = 'printer'
          AND idx.indisunique = true
          AND a.attname = 'ip_address'
          AND NOT idx.indisprimary
    """)
    )
    for row in result:
        conn.execute(sa.text(f'DROP INDEX IF EXISTS "{row[0]}"'))
        return


def upgrade() -> None:
    op.add_column("printer", sa.Column("connection_type", sa.String(length=10), nullable=False, server_default="ip"))
    op.add_column("printer", sa.Column("host_pc", sa.String(length=255), nullable=True))
    op.alter_column("printer", "ip_address", existing_type=sa.String(length=45), nullable=True)
    conn = op.get_bind()
    _drop_unique_on_ip(conn)


def downgrade() -> None:
    op.create_unique_constraint("printer_ip_address_key", "printer", ["ip_address"])
    op.alter_column("printer", "ip_address", existing_type=sa.String(length=45), nullable=False)
    op.drop_column("printer", "host_pc")
    op.drop_column("printer", "connection_type")
