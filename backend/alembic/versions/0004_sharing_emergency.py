"""SMART Health Links, emergency sessions, handovers and notifications.

Revision ID: 0004_sharing_emergency
Revises: 0003_profile
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_sharing_emergency"
down_revision = "0003_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shl_links",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "patient_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("clinical.patients.id"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("manifest_id_hash", sa.LargeBinary(32), nullable=False, unique=True),
        sa.Column("key_enc", sa.LargeBinary(), nullable=False),
        sa.Column("flags", sa.String(4), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("exp", sa.DateTime(timezone=True)),
        sa.Column("passcode_hash", sa.Text()),
        sa.Column("passcode_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        schema="sharing",
    )
    op.create_index(
        "uq_active_emergency_link",
        "shl_links",
        ["patient_id"],
        unique=True,
        schema="sharing",
        postgresql_where=sa.text("kind = 'emergency' AND status = 'active'"),
    )
    op.create_index("ix_links_patient", "shl_links", ["patient_id"], schema="sharing")
    op.create_table(
        "emergency_sessions",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "link_id", sa.UUID(as_uuid=True), sa.ForeignKey("sharing.shl_links.id"), nullable=False
        ),
        sa.Column(
            "patient_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("clinical.patients.id"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("actor_user_id", sa.UUID(as_uuid=True), sa.ForeignKey("identity.users.id")),
        sa.Column("org_id", sa.UUID(as_uuid=True), sa.ForeignKey("identity.organisations.id")),
        sa.Column("reason_enc", sa.LargeBinary()),
        sa.Column("ip_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        schema="sharing",
    )
    op.create_index(
        "ix_emergency_link_time",
        "emergency_sessions",
        ["link_id", "created_at"],
        schema="sharing",
    )
    op.create_index(
        "ix_emergency_ip_time",
        "emergency_sessions",
        ["ip_hash", "created_at"],
        schema="sharing",
    )
    op.create_table(
        "handoffs",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "patient_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("clinical.patients.id"),
            nullable=False,
        ),
        sa.Column(
            "emergency_session_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("sharing.emergency_sessions.id"),
            nullable=False,
        ),
        sa.Column(
            "from_org_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("identity.organisations.id"),
            nullable=False,
        ),
        sa.Column(
            "to_facility_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("identity.organisations.id"),
            nullable=False,
        ),
        sa.Column("priority", sa.String(8), nullable=False),
        sa.Column("eta_minutes", sa.Integer(), nullable=False),
        sa.Column("observations_enc", sa.LargeBinary(), nullable=False),
        sa.Column("notes_enc", sa.LargeBinary()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("idempotency_key", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "emergency_session_id", "idempotency_key", name="uq_handoff_idempotency"
        ),
        schema="sharing",
    )
    op.create_index(
        "ix_handoffs_facility_status",
        "handoffs",
        ["to_facility_id", "status", "created_at"],
        schema="sharing",
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "patient_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("clinical.patients.id"),
            nullable=False,
        ),
        sa.Column("event_seq", sa.BigInteger(), sa.ForeignKey("audit.events.seq"), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="audit",
    )
    op.create_index(
        "ix_notifications_patient_event",
        "notifications",
        ["patient_id", "event_seq"],
        schema="audit",
    )
    op.create_table(
        "manifest_lookups",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("ip_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("known", sa.Boolean(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        schema="ops",
    )
    op.create_index(
        "ix_manifest_lookups_ip_time", "manifest_lookups", ["ip_hash", "ts"], schema="ops"
    )
    op.create_table(
        "breakglass_accesses",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("link_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("ip_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        schema="ops",
    )
    op.create_index(
        "ix_breakglass_link_time", "breakglass_accesses", ["link_id", "ts"], schema="ops"
    )
    op.create_index("ix_breakglass_ip_time", "breakglass_accesses", ["ip_hash", "ts"], schema="ops")

    for table, schema in (
        ("shl_links", "sharing"),
        ("emergency_sessions", "sharing"),
        ("handoffs", "sharing"),
        ("notifications", "audit"),
    ):
        op.execute(f"ALTER TABLE {schema}.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY patient_scope ON {schema}.{table} TO fl_app, fl_worker "
            "USING (patient_id::text = current_setting('firstlook.patient_id', true)) "
            "WITH CHECK (patient_id::text = current_setting('firstlook.patient_id', true))"
        )
    op.execute(
        "CREATE POLICY facility_scope ON sharing.handoffs FOR SELECT TO fl_app "
        "USING (to_facility_id::text = current_setting('firstlook.org_id', true))"
    )
    op.execute(
        "CREATE FUNCTION sharing.patient_id_for_manifest(manifest_hash bytea) RETURNS uuid "
        "LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, sharing AS $$ "
        "SELECT patient_id FROM sharing.shl_links WHERE manifest_id_hash = manifest_hash LIMIT 1 $$"
    )
    op.execute("REVOKE ALL ON FUNCTION sharing.patient_id_for_manifest(bytea) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION sharing.patient_id_for_manifest(bytea) TO fl_app")
    op.execute(
        "CREATE FUNCTION sharing.patient_id_for_session(session_id uuid) RETURNS uuid "
        "LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, sharing AS $$ "
        "SELECT patient_id FROM sharing.emergency_sessions WHERE id = session_id LIMIT 1 $$"
    )
    op.execute("REVOKE ALL ON FUNCTION sharing.patient_id_for_session(uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION sharing.patient_id_for_session(uuid) TO fl_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION sharing.patient_id_for_session(uuid)")
    op.execute("DROP FUNCTION sharing.patient_id_for_manifest(bytea)")
    for table, schema in (
        ("breakglass_accesses", "ops"),
        ("manifest_lookups", "ops"),
        ("notifications", "audit"),
        ("handoffs", "sharing"),
        ("emergency_sessions", "sharing"),
        ("shl_links", "sharing"),
    ):
        op.drop_table(table, schema=schema)
