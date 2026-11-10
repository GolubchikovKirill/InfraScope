"""Separate observed RustDesk IDs from installation targets."""
import sqlalchemy as sa

from alembic import op

revision = "20261110_remote_id"
down_revision = "20261110_toner"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("remoteaccessdevice", sa.Column("observed_rustdesk_id", sa.String(32), nullable=True))
    op.execute("UPDATE remoteaccessdevice SET observed_rustdesk_id = rustdesk_id")


def downgrade():
    op.drop_column("remoteaccessdevice", "observed_rustdesk_id")
