#!/bin/sh
set -eu

# Runs once on a new PostgreSQL data volume. Secret values never enter stdout.
for role in app vault worker migrator; do
    dsn=$(cat "/run/secrets/fl_db_${role}")
    password=${dsn#*://fl_${role}:}
    password=${password%@*}
    if [ "$password" = "$dsn" ] || [ "${#password}" -ne 48 ]; then
        echo "invalid database role secret" >&2
        exit 1
    fi
    case "$password" in
        *[!0-9a-f]*) echo "invalid database role secret" >&2; exit 1 ;;
    esac
    # Passwords are generated as hex; keep them off the psql command line.
    printf "CREATE ROLE fl_%s LOGIN PASSWORD '%s';\n" "$role" "$password" |
        psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null
done

psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'SQL'
REVOKE ALL ON DATABASE firstlook FROM PUBLIC;
GRANT CONNECT ON DATABASE firstlook TO fl_app, fl_vault, fl_worker, fl_migrator;
GRANT CREATE ON DATABASE firstlook TO fl_migrator;
GRANT CREATE ON SCHEMA public TO fl_migrator;
SQL
