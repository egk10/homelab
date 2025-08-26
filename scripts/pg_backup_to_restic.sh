#!/usr/bin/env bash
# pg_backup_to_restic.sh
# Dump the Immich Postgres database and push the dump to a restic repo (S3/RGW).
# Requirements:
# - restic installed and RESTIC_REPOSITORY + RESTIC_PASSWORD set in environment
# - psql/pg_dump installed and the script run on the Docker host with access to the Postgres instance
# - .env present (this script will source it)

set -euo pipefail

if [ -f .env ]; then
  # shellcheck disable=SC1091
  set -a
  . .env
  set +a
fi

DB_HOST=${DB_HOSTNAME:-localhost}
DB_PORT=${DB_PORT:-5432}
DB_USER=${POSTGRES_USER:-immich}
DB_NAME=${POSTGRES_DB:-immich}

if [ -z "${RESTIC_REPOSITORY:-}" ] || [ -z "${RESTIC_PASSWORD:-}" ]; then
  echo "Set RESTIC_REPOSITORY and RESTIC_PASSWORD in environment before running." >&2
  exit 2
fi

TS="$(date -u +%Y%m%dT%H%M%SZ)"
DUMP_FILE="/tmp/immich-db-dump-${TS}.sql.gz"

echo "Creating pg dump for database: ${DB_NAME}"
export PGPASSWORD="${POSTGRES_PASSWORD}"
pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -Fc "$DB_NAME" | gzip > "$DUMP_FILE"

echo "Dump created: $DUMP_FILE"

# Ensure restic can access the repo
if ! restic snapshots >/dev/null 2>&1; then
  echo "Restic repo not accessible or not initialized. Run restic init or check RESTIC env vars." >&2
  exit 3
fi

echo "Backing up dump to restic"
restic backup "$DUMP_FILE" --tag immich-db-backup

# Optionally remove local dump
rm -f "$DUMP_FILE"

echo "Backup complete. Keep retention policy on restic to control retention."

exit 0
