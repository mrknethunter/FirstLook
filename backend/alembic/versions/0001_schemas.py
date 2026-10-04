"""Create the schema boundaries and default privileges.

Revision ID: 0001_schemas
Revises:
"""

from alembic import op

revision = "0001_schemas"
down_revision = None
branch_labels = None
depends_on = None

SCHEMAS = ("identity", "vault", "clinical", "telemetry", "sharing", "audit", "ops", "terminology")


def upgrade() -> None:
    for schema in SCHEMAS:
        op.execute(f"CREATE SCHEMA {schema} AUTHORIZATION fl_migrator")
    op.execute(
        "GRANT USAGE ON SCHEMA identity, clinical, telemetry, sharing, audit, ops, "
        "terminology TO fl_app"
    )
    op.execute("GRANT USAGE ON SCHEMA vault TO fl_vault")
    op.execute("GRANT USAGE ON SCHEMA clinical, telemetry, audit, ops TO fl_worker")
    for schema in ("identity", "clinical", "telemetry", "sharing", "ops"):
        op.execute(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE fl_migrator IN SCHEMA {schema} "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO fl_app"
        )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE fl_migrator IN SCHEMA terminology "
        "GRANT SELECT ON TABLES TO fl_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE fl_migrator IN SCHEMA vault "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO fl_vault"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE fl_migrator IN SCHEMA audit "
        "GRANT SELECT, INSERT ON TABLES TO fl_app"
    )
    for schema in ("clinical", "telemetry", "ops"):
        op.execute(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE fl_migrator IN SCHEMA {schema} "
            "GRANT SELECT, INSERT, UPDATE ON TABLES TO fl_worker"
        )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE fl_migrator IN SCHEMA audit "
        "GRANT INSERT ON TABLES TO fl_worker"
    )
    for schema in ("identity", "clinical", "telemetry", "sharing", "ops", "audit"):
        op.execute(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE fl_migrator IN SCHEMA {schema} "
            "GRANT USAGE, SELECT ON SEQUENCES TO fl_app"
        )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE fl_migrator IN SCHEMA audit "
        "GRANT USAGE, SELECT ON SEQUENCES TO fl_worker"
    )


def downgrade() -> None:
    for schema in reversed(SCHEMAS):
        op.execute(f"DROP SCHEMA {schema} CASCADE")
