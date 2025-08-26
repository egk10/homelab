#!/usr/bin/env bash
# init_restic_repo.sh
# Initialize an encrypted restic repo on Ceph RGW (S3). Run on a host with restic and AWS env vars set.

set -euo pipefail

usage() {
  cat <<EOF
Usage: $0
Environment variables required (example):
  AWS_ACCESS_KEY_ID
  AWS_SECRET_ACCESS_KEY
  RESTIC_PASSWORD (strong password used to encrypt the repo)
  RESTIC_REPOSITORY (e.g. s3:http://rgw-host:80/backup-bucket)

This script will:
 - check restic is installed
 - initialize repo if not present
EOF
  exit 1
}

if [ "${RESTIC_REPOSITORY:-}" = "" ]; then
  echo "RESTIC_REPOSITORY not set. Example: export RESTIC_REPOSITORY='s3:http://rgw-host:80/backup-bucket'"; exit 2
fi

command -v restic >/dev/null 2>&1 || { echo "restic not found. Install restic and retry."; exit 2; }

if [ -z "${RESTIC_PASSWORD:-}" ]; then
  echo "RESTIC_PASSWORD is not set. Set it in environment before running."; exit 2
fi

# Initialize
if restic snapshots >/dev/null 2>&1; then
  echo "Restic repository appears to exist and is accessible. Use 'restic snapshots' and 'restic snapshots --path' to inspect."
else
  echo "Initializing restic repository: $RESTIC_REPOSITORY"
  restic init
  echo "Repository initialized. Test by running a small backup command and then 'restic snapshots'"
fi

exit 0
