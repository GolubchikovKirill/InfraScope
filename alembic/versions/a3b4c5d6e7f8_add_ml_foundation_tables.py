"""add ml foundation tables

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-02-24 00:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3b4c5d6e7f8"
down_revision: str | Sequence[str] | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mlfeaturesnapshot",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_kind", sa.String(length=32), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("device_name", sa.String(length=255), nullable=True),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("is_online", sa.Boolean(), nullable=True),
        sa.Column("toner_color", sa.String(length=16), nullable=True),
        sa.Column("toner_level", sa.Integer(), nullable=True),
        sa.Column("toner_model", sa.String(length=128), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("hour_of_day", sa.Integer(), nullable=False),
        sa.Column("day_of_week", sa.Integer(), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_mlfeaturesnapshot_device_kind"), "mlfeaturesnapshot", ["device_kind"], unique=False)
    op.create_index(op.f("ix_mlfeaturesnapshot_device_id"), "mlfeaturesnapshot", ["device_id"], unique=False)
    op.create_index(op.f("ix_mlfeaturesnapshot_device_name"), "mlfeaturesnapshot", ["device_name"], unique=False)
    op.create_index(op.f("ix_mlfeaturesnapshot_address"), "mlfeaturesnapshot", ["address"], unique=False)
    op.create_index(op.f("ix_mlfeaturesnapshot_is_online"), "mlfeaturesnapshot", ["is_online"], unique=False)
    op.create_index(op.f("ix_mlfeaturesnapshot_toner_color"), "mlfeaturesnapshot", ["toner_color"], unique=False)
    op.create_index(op.f("ix_mlfeaturesnapshot_toner_model"), "mlfeaturesnapshot", ["toner_model"], unique=False)
    op.create_index(op.f("ix_mlfeaturesnapshot_source"), "mlfeaturesnapshot", ["source"], unique=False)
    op.create_index(op.f("ix_mlfeaturesnapshot_hour_of_day"), "mlfeaturesnapshot", ["hour_of_day"], unique=False)
    op.create_index(op.f("ix_mlfeaturesnapshot_day_of_week"), "mlfeaturesnapshot", ["day_of_week"], unique=False)
    op.create_index(op.f("ix_mlfeaturesnapshot_captured_at"), "mlfeaturesnapshot", ["captured_at"], unique=False)

    op.create_table(
        "mlmodelregistry",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("model_family", sa.String(length=32), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("train_rows", sa.Integer(), nullable=False),
        sa.Column("metric_primary", sa.Float(), nullable=True),
        sa.Column("metric_secondary", sa.Float(), nullable=True),
        sa.Column("metadata_json", sa.String(length=16000), nullable=True),
        sa.Column("trained_at", sa.DateTime(), nullable=False),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_mlmodelregistry_model_family"), "mlmodelregistry", ["model_family"], unique=False)
    op.create_index(op.f("ix_mlmodelregistry_version"), "mlmodelregistry", ["version"], unique=False)
    op.create_index(op.f("ix_mlmodelregistry_status"), "mlmodelregistry", ["status"], unique=False)
    op.create_index(op.f("ix_mlmodelregistry_trained_at"), "mlmodelregistry", ["trained_at"], unique=False)
    op.create_index(op.f("ix_mlmodelregistry_activated_at"), "mlmodelregistry", ["activated_at"], unique=False)

    op.create_table(
        "mltonerprediction",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("printer_id", sa.Uuid(), nullable=True),
        sa.Column("printer_name", sa.String(length=255), nullable=True),
        sa.Column("toner_color", sa.String(length=16), nullable=False),
        sa.Column("toner_model", sa.String(length=128), nullable=True),
        sa.Column("current_level", sa.Integer(), nullable=True),
        sa.Column("days_to_replacement", sa.Float(), nullable=True),
        sa.Column("predicted_replacement_at", sa.DateTime(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_mltonerprediction_printer_id"), "mltonerprediction", ["printer_id"], unique=False)
    op.create_index(op.f("ix_mltonerprediction_printer_name"), "mltonerprediction", ["printer_name"], unique=False)
    op.create_index(op.f("ix_mltonerprediction_toner_color"), "mltonerprediction", ["toner_color"], unique=False)
    op.create_index(
        op.f("ix_mltonerprediction_days_to_replacement"), "mltonerprediction", ["days_to_replacement"], unique=False
    )
    op.create_index(
        op.f("ix_mltonerprediction_predicted_replacement_at"),
        "mltonerprediction",
        ["predicted_replacement_at"],
        unique=False,
    )
    op.create_index(op.f("ix_mltonerprediction_model_version"), "mltonerprediction", ["model_version"], unique=False)
    op.create_index(op.f("ix_mltonerprediction_created_at"), "mltonerprediction", ["created_at"], unique=False)

    op.create_table(
        "mlofflineriskprediction",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_kind", sa.String(length=32), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("device_name", sa.String(length=255), nullable=True),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_mlofflineriskprediction_device_kind"), "mlofflineriskprediction", ["device_kind"], unique=False
    )
    op.create_index(
        op.f("ix_mlofflineriskprediction_device_id"), "mlofflineriskprediction", ["device_id"], unique=False
    )
    op.create_index(
        op.f("ix_mlofflineriskprediction_device_name"), "mlofflineriskprediction", ["device_name"], unique=False
    )
    op.create_index(op.f("ix_mlofflineriskprediction_address"), "mlofflineriskprediction", ["address"], unique=False)
    op.create_index(
        op.f("ix_mlofflineriskprediction_risk_score"), "mlofflineriskprediction", ["risk_score"], unique=False
    )
    op.create_index(
        op.f("ix_mlofflineriskprediction_risk_level"), "mlofflineriskprediction", ["risk_level"], unique=False
    )
    op.create_index(
        op.f("ix_mlofflineriskprediction_model_version"), "mlofflineriskprediction", ["model_version"], unique=False
    )
    op.create_index(
        op.f("ix_mlofflineriskprediction_created_at"), "mlofflineriskprediction", ["created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_mlofflineriskprediction_created_at"), table_name="mlofflineriskprediction")
    op.drop_index(op.f("ix_mlofflineriskprediction_model_version"), table_name="mlofflineriskprediction")
    op.drop_index(op.f("ix_mlofflineriskprediction_risk_level"), table_name="mlofflineriskprediction")
    op.drop_index(op.f("ix_mlofflineriskprediction_risk_score"), table_name="mlofflineriskprediction")
    op.drop_index(op.f("ix_mlofflineriskprediction_address"), table_name="mlofflineriskprediction")
    op.drop_index(op.f("ix_mlofflineriskprediction_device_name"), table_name="mlofflineriskprediction")
    op.drop_index(op.f("ix_mlofflineriskprediction_device_id"), table_name="mlofflineriskprediction")
    op.drop_index(op.f("ix_mlofflineriskprediction_device_kind"), table_name="mlofflineriskprediction")
    op.drop_table("mlofflineriskprediction")

    op.drop_index(op.f("ix_mltonerprediction_created_at"), table_name="mltonerprediction")
    op.drop_index(op.f("ix_mltonerprediction_model_version"), table_name="mltonerprediction")
    op.drop_index(op.f("ix_mltonerprediction_predicted_replacement_at"), table_name="mltonerprediction")
    op.drop_index(op.f("ix_mltonerprediction_days_to_replacement"), table_name="mltonerprediction")
    op.drop_index(op.f("ix_mltonerprediction_toner_color"), table_name="mltonerprediction")
    op.drop_index(op.f("ix_mltonerprediction_printer_name"), table_name="mltonerprediction")
    op.drop_index(op.f("ix_mltonerprediction_printer_id"), table_name="mltonerprediction")
    op.drop_table("mltonerprediction")

    op.drop_index(op.f("ix_mlmodelregistry_activated_at"), table_name="mlmodelregistry")
    op.drop_index(op.f("ix_mlmodelregistry_trained_at"), table_name="mlmodelregistry")
    op.drop_index(op.f("ix_mlmodelregistry_status"), table_name="mlmodelregistry")
    op.drop_index(op.f("ix_mlmodelregistry_version"), table_name="mlmodelregistry")
    op.drop_index(op.f("ix_mlmodelregistry_model_family"), table_name="mlmodelregistry")
    op.drop_table("mlmodelregistry")

    op.drop_index(op.f("ix_mlfeaturesnapshot_captured_at"), table_name="mlfeaturesnapshot")
    op.drop_index(op.f("ix_mlfeaturesnapshot_day_of_week"), table_name="mlfeaturesnapshot")
    op.drop_index(op.f("ix_mlfeaturesnapshot_hour_of_day"), table_name="mlfeaturesnapshot")
    op.drop_index(op.f("ix_mlfeaturesnapshot_source"), table_name="mlfeaturesnapshot")
    op.drop_index(op.f("ix_mlfeaturesnapshot_toner_model"), table_name="mlfeaturesnapshot")
    op.drop_index(op.f("ix_mlfeaturesnapshot_toner_color"), table_name="mlfeaturesnapshot")
    op.drop_index(op.f("ix_mlfeaturesnapshot_is_online"), table_name="mlfeaturesnapshot")
    op.drop_index(op.f("ix_mlfeaturesnapshot_address"), table_name="mlfeaturesnapshot")
    op.drop_index(op.f("ix_mlfeaturesnapshot_device_name"), table_name="mlfeaturesnapshot")
    op.drop_index(op.f("ix_mlfeaturesnapshot_device_id"), table_name="mlfeaturesnapshot")
    op.drop_index(op.f("ix_mlfeaturesnapshot_device_kind"), table_name="mlfeaturesnapshot")
    op.drop_table("mlfeaturesnapshot")
