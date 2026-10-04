"""Encrypted clinical resources, Essentials selection and terminology.

Revision ID: 0003_profile
Revises: 0002_identity_security
"""

import json
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003_profile"
down_revision = "0002_identity_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("persons", sa.Column("gender_enc", sa.LargeBinary()), schema="vault")
    op.add_column("persons", sa.Column("age_band_enc", sa.LargeBinary()), schema="vault")
    op.create_table(
        "resources",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "patient_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("clinical.patients.id"),
            nullable=False,
        ),
        sa.Column("rtype", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("fhir_enc", sa.LargeBinary(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema="clinical",
    )
    op.create_index(
        "ix_resources_patient_type", "resources", ["patient_id", "rtype"], schema="clinical"
    )
    op.create_table(
        "contacts",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "patient_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("clinical.patients.id"),
            nullable=False,
        ),
        sa.Column("data_enc", sa.LargeBinary(), nullable=False),
        sa.Column("notify_on_access", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="clinical",
    )
    op.create_table(
        "essentials_selection",
        sa.Column(
            "patient_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("clinical.patients.id"),
            primary_key=True,
        ),
        sa.Column("items", JSONB(), nullable=False),
        sa.Column("show_sex", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema="clinical",
    )
    op.create_table(
        "confirmations",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "patient_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("clinical.patients.id"),
            nullable=False,
        ),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sections", JSONB(), nullable=False),
        schema="clinical",
    )
    op.create_table(
        "code_display",
        sa.Column("system", sa.String(200), primary_key=True),
        sa.Column("code", sa.String(80), primary_key=True),
        sa.Column("lang", sa.String(2), primary_key=True),
        sa.Column("display", sa.String(240), nullable=False),
        schema="terminology",
    )
    op.create_table(
        "med_products",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("strength", sa.String(80)),
        sa.Column("form", sa.String(80)),
        sa.Column("atc_code", sa.String(16)),
        sa.Column("atc_prefix", sa.String(8)),
        sa.Column("substances", JSONB(), nullable=False),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("code_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="terminology",
    )
    op.create_index("ix_med_products_name", "med_products", ["name"], schema="terminology")
    op.create_table(
        "demo_personas",
        sa.Column("persona", sa.String(16), primary_key=True),
        sa.Column(
            "patient_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("clinical.patients.id"),
            nullable=False,
        ),
        schema="ops",
    )

    displays = [
        ("http://www.whocc.no/atc", "B01AF02", "apixaban", "apiksaban", "apixaban"),
        ("http://www.whocc.no/atc", "A10BA02", "metformin", "metformina", "metformina"),
        ("http://www.whocc.no/atc", "M01AE01", "ibuprofen", "ibuprofen", "ibuprofene"),
        (
            "http://hl7.org/fhir/sid/icd-10",
            "E10",
            "type 1 diabetes",
            "cukrzyca typu 1",
            "diabete di tipo 1",
        ),
        (
            "http://snomed.info/sct",
            "14106009",
            "cardiac pacemaker",
            "rozrusznik serca",
            "pacemaker cardiaco",
        ),
    ]
    for system, code, en, pl, it in displays:
        for lang, display in (("en", en), ("pl", pl), ("it", it)):
            op.execute(
                sa.text(
                    "INSERT INTO terminology.code_display (system, code, lang, display) "
                    "VALUES (:system, :code, :lang, :display)"
                ).bindparams(system=system, code=code, lang=lang, display=display)
            )

    # Substance codes: WHO ATC/DDD Index. No invented dose or product assignment.
    catalogue = [
        ("apixaban", None, None, "B01AF02", "B01AF", ["apixaban"], "WHO ATC/DDD Index", True),
        ("metformin", None, None, "A10BA02", "A10B", ["metformin"], "WHO ATC/DDD Index", True),
        ("ibuprofen", None, None, "M01AE01", None, ["ibuprofen"], "WHO ATC/DDD Index", True),
        (
            "Glucophage",
            "500 mg",
            "film-coated tablet",
            "A10BA02",
            "A10B",
            ["metformin hydrochloride"],
            "Polish RPL 22922",
            True,
        ),
    ]
    for name, strength, form, atc_code, atc_prefix, substances, source, verified in catalogue:
        op.execute(
            sa.text(
                "INSERT INTO terminology.med_products "
                "(id, name, strength, form, atc_code, atc_prefix, "
                "substances, source, code_verified) "
                "VALUES (:id, :name, :strength, :form, :atc_code, :atc_prefix, "
                "CAST(:substances AS jsonb), :source, :verified)"
            ).bindparams(
                id=uuid5(NAMESPACE_URL, f"firstlook-med:{name}:{strength}"),
                name=name,
                strength=strength,
                form=form,
                atc_code=atc_code,
                atc_prefix=atc_prefix,
                substances=json.dumps(substances),
                source=source,
                verified=verified,
            )
        )

    for table in ("resources", "contacts", "essentials_selection", "confirmations"):
        op.execute(f"ALTER TABLE clinical.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY patient_scope ON clinical.{table} TO fl_app, fl_worker "
            "USING (patient_id::text = current_setting('firstlook.patient_id', true)) "
            "WITH CHECK (patient_id::text = current_setting('firstlook.patient_id', true))"
        )

    # Resolve only the signed-in owner's pseudonymous ID before setting RLS scope.
    op.execute(
        "CREATE FUNCTION clinical.patient_id_for_owner(owner_id uuid) RETURNS uuid "
        "LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, clinical AS $$ "
        "SELECT id FROM clinical.patients "
        "WHERE owner_user_id = owner_id AND deleted_at IS NULL LIMIT 1 $$"
    )
    op.execute("REVOKE ALL ON FUNCTION clinical.patient_id_for_owner(uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION clinical.patient_id_for_owner(uuid) TO fl_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION clinical.patient_id_for_owner(uuid)")
    for table, schema in (
        ("demo_personas", "ops"),
        ("med_products", "terminology"),
        ("code_display", "terminology"),
        ("confirmations", "clinical"),
        ("essentials_selection", "clinical"),
        ("contacts", "clinical"),
        ("resources", "clinical"),
    ):
        op.drop_table(table, schema=schema)
    op.drop_column("persons", "age_band_enc", schema="vault")
    op.drop_column("persons", "gender_enc", schema="vault")
