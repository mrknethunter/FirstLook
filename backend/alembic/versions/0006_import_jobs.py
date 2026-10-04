"""PostgreSQL job queue and encrypted import staging.

Revision ID: 0006_import_jobs
Revises: 0005_telemetry
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006_import_jobs"
down_revision = "0005_telemetry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_by", sa.String(80)),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(80)),
        schema="ops",
    )
    op.create_index("ix_jobs_due", "jobs", ["status", "run_after"], schema="ops")
    op.create_table(
        "import_files",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "patient_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("clinical.patients.id"),
            nullable=False,
        ),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("parsed_at", sa.DateTime(timezone=True)),
        sa.Column("committed_at", sa.DateTime(timezone=True)),
        sa.Column("preview_enc", sa.LargeBinary()),
        sa.Column("report_enc", sa.LargeBinary()),
        schema="ops",
    )
    op.create_index("ix_import_patient", "import_files", ["patient_id", "created_at"], schema="ops")
    op.create_index("ix_import_expiry", "import_files", ["expires_at"], schema="ops")
    op.execute("ALTER TABLE ops.import_files ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY patient_scope ON ops.import_files TO fl_app, fl_worker "
        "USING (patient_id::text = current_setting('firstlook.patient_id', true)) "
        "WITH CHECK (patient_id::text = current_setting('firstlook.patient_id', true))"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON ops.import_files TO fl_worker")
    op.execute(
        "CREATE FUNCTION ops.expired_imports() RETURNS TABLE(id uuid, patient_id uuid) "
        "LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, ops AS $$ "
        "SELECT i.id, i.patient_id FROM ops.import_files AS i WHERE i.expires_at <= now() "
        "AND i.status NOT IN ('committed', 'expired') $$"
    )
    op.execute("REVOKE ALL ON FUNCTION ops.expired_imports() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION ops.expired_imports() TO fl_worker")
    op.execute(
        "CREATE FUNCTION clinical.active_patient_ids() RETURNS SETOF uuid "
        "LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, clinical AS $$ "
        "SELECT id FROM clinical.patients WHERE deleted_at IS NULL $$"
    )
    op.execute("REVOKE ALL ON FUNCTION clinical.active_patient_ids() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION clinical.active_patient_ids() TO fl_worker")


def downgrade() -> None:
    op.execute("DROP FUNCTION clinical.active_patient_ids()")
    op.execute("DROP FUNCTION ops.expired_imports()")
    op.drop_table("import_files", schema="ops")
    op.drop_table("jobs", schema="ops")
