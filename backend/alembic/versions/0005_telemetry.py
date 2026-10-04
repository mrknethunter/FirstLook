"""Wearable aggregates and personal baselines.

Revision ID: 0005_telemetry
Revises: 0004_sharing_emergency
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_telemetry"
down_revision = "0004_sharing_emergency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_metrics",
        sa.Column(
            "patient_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("clinical.patients.id"),
            primary_key=True,
        ),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("metric", sa.String(32), primary_key=True),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(24), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        schema="telemetry",
    )
    op.create_table(
        "hourly_metrics",
        sa.Column(
            "patient_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("clinical.patients.id"),
            primary_key=True,
        ),
        sa.Column("hour", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("metric", sa.String(32), primary_key=True),
        sa.Column("value", sa.Float(), nullable=False),
        schema="telemetry",
    )
    op.create_table(
        "baselines",
        sa.Column(
            "patient_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("clinical.patients.id"),
            primary_key=True,
        ),
        sa.Column("metric", sa.String(32), primary_key=True),
        sa.Column("window_days", sa.Integer(), primary_key=True),
        sa.Column("median", sa.Float(), nullable=False),
        sa.Column("mad", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        schema="telemetry",
    )
    op.create_table(
        "sync_state",
        sa.Column(
            "patient_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("clinical.patients.id"),
            primary_key=True,
        ),
        sa.Column("last_sync_at", sa.DateTime(timezone=True)),
        sa.Column("last_activity_at", sa.DateTime(timezone=True)),
        sa.Column("source", sa.String(32), nullable=False),
        schema="telemetry",
    )
    for table in ("daily_metrics", "hourly_metrics", "baselines", "sync_state"):
        op.execute(f"ALTER TABLE telemetry.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY patient_scope ON telemetry.{table} TO fl_app, fl_worker "
            "USING (patient_id::text = current_setting('firstlook.patient_id', true)) "
            "WITH CHECK (patient_id::text = current_setting('firstlook.patient_id', true))"
        )
    op.execute("GRANT DELETE ON telemetry.hourly_metrics, telemetry.baselines TO fl_worker")


def downgrade() -> None:
    for table in ("sync_state", "baselines", "hourly_metrics", "daily_metrics"):
        op.drop_table(table, schema="telemetry")
