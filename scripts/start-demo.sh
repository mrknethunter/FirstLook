#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
    cat > .env <<'ENV'
FL_ENV=demo
FL_PUBLIC_BASE_URL=https://firstlook-hy-demo.duckdns.org
FL_SUPPORTED_LOCALES=en,pl,it
FL_LOG_DIR=/var/log/firstlook
FL_LOG_LEVEL=INFO
FL_BREAKGLASS_LINK_LIMIT=50
FL_BREAKGLASS_IP_LIMIT=100
FL_SESSION_TTL_PATIENT_MINUTES=30
FL_SESSION_TTL_PROFESSIONAL_HOURS=12
FL_SESSION_TTL_BREAKGLASS_MINUTES=15
FL_DEMO_TENANT_ENABLED=true
FL_OPENAPI_ENABLED=true
FL_DEMO_JUDGE_TABLES=3
ENV
fi
if ! grep -qx 'FL_ENV=demo' .env || ! grep -qx 'FL_DEMO_TENANT_ENABLED=true' .env; then
    echo 'start-demo.sh requires .env to select the isolated demo tenant.' >&2
    exit 1
fi

mkdir -p secrets
chmod 700 secrets
secret_hex() { [[ -f "secrets/$1" ]] || openssl rand -hex "$2" > "secrets/$1"; }
secret_hex pg_super_password 32
secret_hex fl_kek 32
secret_hex fl_pepper 32
printf 'postgres\n' > secrets/pg_super_user
for role in app vault worker migrator; do
    if [[ ! -f "secrets/fl_db_${role}" ]]; then
        password=$(openssl rand -hex 24)
        printf 'postgresql+psycopg://fl_%s:%s@db:5432/firstlook\n' "$role" "$password" > "secrets/fl_db_${role}"
    fi
done
if [[ ! -f secrets/demo_credentials.tsv ]]; then
    tables=$(sed -n 's/^FL_DEMO_JUDGE_TABLES=//p' .env | tail -n 1 | tr -d '\r')
    tables=${tables:-3}
    if [[ ! $tables =~ ^[1-9][0-9]*$ ]] || (( tables > 30 )); then
        echo 'invalid FL_DEMO_JUDGE_TABLES' >&2
        exit 1
    fi
    {
        printf 'patient_anna\t%s\n' "$(openssl rand -hex 12)"
        printf 'patient_marco\t%s\n' "$(openssl rand -hex 12)"
        for ((table = 1; table <= tables; table++)); do
            printf 'responder_%s\t%s\n' "$table" "$(openssl rand -hex 12)"
            printf 'ed_staff_%s\t%s\n' "$table" "$(openssl rand -hex 12)"
        done
    } > secrets/demo_credentials.tsv
    echo 'Created secrets/demo_credentials.tsv. Reuse this file for the same demo logins on every deployment.'
fi
# Compose file secrets are bind mounts. The enclosing host directory remains 0700.
chmod 644 secrets/*

docker compose up --build -d
docker compose run --rm seed
echo 'FirstLook containers started. Check: docker compose ps'
echo 'Host Caddy must use Caddyfile.example; the script does not edit Caddy.'
