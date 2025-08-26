#!/usr/bin/env bash
# preflight_checks.sh - simple checks before deploying the compose stack
# Usage: ./scripts/preflight_checks.sh

set -euo pipefail

REQUIRED_ENV_VARS=(
  POSTGRES_PASSWORD
  REDIS_PASSWORD
  MYSQL_ROOT_PASSWORD
  MYSQL_PASSWORD
  CEPH_S3_ACCESS_KEY_ID
  CEPH_S3_SECRET_ACCESS_KEY
  CEPH_S3_ENDPOINT
  ADMIN_TOKEN
)

# If .env exists in repo root, source it (non-exporting by default)
if [ -f .env ]; then
  # shellcheck disable=SC1091
  set -a
  . .env
  set +a
  echo "Loaded .env file"
fi

check_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "MISSING: command '$1' not found"
    return 1
  fi
  echo "OK:     $1"
}

echo "== Basic command checks =="
check_cmd docker || true
check_cmd docker-compose || true
check_cmd docker || true
check_cmd ceph || true
check_cmd radosgw-admin || echo "Note: radosgw-admin not found; RGW user creation must run on a Ceph admin node"

echo
echo "== Docker Compose config validation =="
if docker compose -f docker-compose.yml config >/dev/null 2>&1; then
  echo "OK: docker compose config is valid"
else
  echo "FAIL: docker compose config has issues"
  docker compose -f docker-compose.yml config || true
fi

echo
echo "== Check Ceph mountpoint =="
if mountpoint -q /mnt/ceph; then
  echo "OK: /mnt/ceph is mounted"
else
  if [ -d /mnt/ceph ]; then
    echo "WARN: /mnt/ceph exists but is not mounted"
  else
    echo "MISSING: /mnt/ceph does not exist. Create and mount CephFS before deploying"
  fi
fi

echo
echo "== Required environment variables =="
missing_env=0
for v in "${REQUIRED_ENV_VARS[@]}"; do
  if [ -z "${!v:-}" ]; then
    echo "MISSING: $v"
    missing_env=1
  else
    echo "OK:     $v"
  fi
done
if [ $missing_env -ne 0 ]; then
  echo
  echo "One or more required environment variables are missing. Copy .env.example to .env and fill values."
fi

echo
echo "== Host directories check =="
HOST_DIRS=(
  /mnt/ceph
  /mnt/ceph/nextcloud
  /mnt/ceph/vaultwarden
  /mnt/ceph/immich
  /home/egk/tsdproxy/config
  /home/egk/tsdproxy/datadir
  /home/egk/homeassist/config
)
for d in "${HOST_DIRS[@]}"; do
  if [ -d "$d" ]; then
    echo "OK:     $d"
  else
    echo "MISSING: $d"
  fi
done

echo
echo "== Summary =="
if [ $missing_env -ne 0 ]; then
  echo "Preflight: NOT READY - fix missing env vars and re-run"
  exit 2
fi

if ! mountpoint -q /mnt/ceph; then
  echo "Preflight: NOT READY - CephFS not mounted at /mnt/ceph"
  exit 3
fi

if ! docker compose -f docker-compose.yml config >/dev/null 2>&1; then
  echo "Preflight: NOT READY - docker compose config invalid"
  exit 4
fi

echo "Preflight: OK - you can proceed to 'docker compose up -d'"
exit 0
