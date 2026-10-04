"""Identity, patient key, consent and append-only audit tables.

Revision ID: 0002_identity_security
Revises: 0001_schemas
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002_identity_security"
down_revision = "0001_schemas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("email_hmac", sa.LargeBinary(32), nullable=False, unique=True),
        sa.Column("email_enc", sa.LargeBinary(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("mfa_secret_enc", sa.LargeBinary()),
        sa.Column("mfa_pending_secret_enc", sa.LargeBinary()),
        sa.Column("locale", sa.String(2), nullable=False, server_default="en"),
        sa.Column("theme", sa.String(8), nullable=False, server_default="system"),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("tenant", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="identity",
    )
    op.create_table(
        "organisations",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("facility_code", sa.String(80), unique=True),
        sa.Column("lat", sa.Float()),
        sa.Column("lon", sa.Float()),
        sa.Column("tenant", sa.String(32), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        schema="identity",
    )
    op.create_table(
        "memberships",
        sa.Column(
            "user_id", sa.UUID(as_uuid=True), sa.ForeignKey("identity.users.id"), primary_key=True
        ),
        sa.Column(
            "org_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("identity.organisations.id"),
            primary_key=True,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        schema="identity",
    )
    op.create_table(
        "sessions",
        sa.Column("id_hash", sa.LargeBinary(32), primary_key=True),
        sa.Column("user_id", sa.UUID(as_uuid=True), sa.ForeignKey("identity.users.id")),
        sa.Column("org_id", sa.UUID(as_uuid=True), sa.ForeignKey("identity.organisations.id")),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("mfa_passed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("ip_hash", sa.LargeBinary(32)),
        sa.Column("ua_hash", sa.LargeBinary(32)),
        schema="identity",
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"], schema="identity")
    op.create_table(
        "mfa_recovery_codes",
        sa.Column(
            "user_id", sa.UUID(as_uuid=True), sa.ForeignKey("identity.users.id"), nullable=False
        ),
        sa.Column("code_hash", sa.LargeBinary(32), primary_key=True),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        schema="identity",
    )
    op.create_index("ix_recovery_codes_user", "mfa_recovery_codes", ["user_id"], schema="identity")
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("email_hmac", sa.LargeBinary(32), nullable=False),
        sa.Column("ip_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("failed", sa.Boolean(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        schema="identity",
    )
    op.create_index(
        "ix_login_attempts_account", "login_attempts", ["email_hmac", "ts"], schema="identity"
    )
    op.create_index("ix_login_attempts_ip", "login_attempts", ["ip_hash", "ts"], schema="identity")
    op.create_table(
        "patients",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("identity.users.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("dek_wrapped", sa.LargeBinary(), nullable=False),
        sa.Column("dek_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("kek_id", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        schema="clinical",
    )
    op.create_table(
        "consents",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "patient_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("clinical.patients.id"),
            nullable=False,
        ),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("policy_version", sa.String(24), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        schema="clinical",
    )
    op.create_index(
        "ix_consents_patient_type_ts", "consents", ["patient_id", "type", "ts"], schema="clinical"
    )
    op.create_table(
        "persons",
        sa.Column("patient_id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("given_enc", sa.LargeBinary()),
        sa.Column("family_enc", sa.LargeBinary()),
        sa.Column("birth_date_enc", sa.LargeBinary()),
        sa.Column("national_id_enc", sa.LargeBinary()),
        sa.Column("phone_enc", sa.LargeBinary()),
        sa.Column("address_enc", sa.LargeBinary()),
        sa.Column("preferred_language", sa.String(2)),
        schema="vault",
    )
    op.create_table(
        "events",
        sa.Column("seq", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("patient_id", sa.UUID(as_uuid=True)),
        sa.Column("actor_type", sa.String(24), nullable=False),
        sa.Column("actor_id", sa.UUID(as_uuid=True)),
        sa.Column("org_id", sa.UUID(as_uuid=True)),
        sa.Column("role", sa.String(24)),
        sa.Column("tier", sa.String(8)),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("purpose", sa.String(80), nullable=False),
        sa.Column("reason_enc", sa.LargeBinary()),
        sa.Column("categories", JSONB(), nullable=False),
        sa.Column("session_ref", sa.UUID(as_uuid=True)),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("canonical", JSONB(), nullable=False),
        sa.Column("prev_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("hash", sa.LargeBinary(32), nullable=False),
        schema="audit",
    )
    op.create_index("ix_events_patient_seq", "events", ["patient_id", "seq"], schema="audit")

    for table, schema, role in (
        ("patients", "clinical", "fl_app, fl_worker"),
        ("consents", "clinical", "fl_app, fl_worker"),
        ("persons", "vault", "fl_vault"),
        ("events", "audit", "fl_app, fl_worker"),
    ):
        op.execute(f"ALTER TABLE {schema}.{table} ENABLE ROW LEVEL SECURITY")
        scoped_column = "id" if table == "patients" else "patient_id"
        op.execute(
            f"CREATE POLICY patient_scope ON {schema}.{table} TO {role} "
            f"USING ({scoped_column}::text = current_setting('firstlook.patient_id', true)) "
            f"WITH CHECK ({scoped_column}::text = current_setting('firstlook.patient_id', true))"
        )

    # This function exposes only the chain head; its owner can read through RLS.
    op.execute(
        "CREATE FUNCTION audit.last_hash() RETURNS bytea LANGUAGE sql SECURITY DEFINER "
        "SET search_path = pg_catalog, audit AS $$ "
        "SELECT hash FROM audit.events ORDER BY seq DESC LIMIT 1 $$"
    )
    op.execute("REVOKE ALL ON FUNCTION audit.last_hash() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION audit.last_hash() TO fl_app, fl_worker")


def downgrade() -> None:
    op.execute("DROP FUNCTION audit.last_hash()")
    for table, schema in (
        ("events", "audit"),
        ("persons", "vault"),
        ("consents", "clinical"),
        ("patients", "clinical"),
        ("login_attempts", "identity"),
        ("mfa_recovery_codes", "identity"),
        ("sessions", "identity"),
        ("memberships", "identity"),
        ("organisations", "identity"),
        ("users", "identity"),
    ):
        op.drop_table(table, schema=schema)
