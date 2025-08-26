#!/usr/bin/env bash
# restic_backup_and_test.sh
# Quick helper to initialize restic repo and run a small backup + restore test.
# Run with environment variables set (see scripts/init_restic_repo.sh usage)

set -euo pipefail

# Ensure restic present
command -v restic >/dev/null 2>&1 || { echo "restic not installed" >&2; exit 2; }

if [ -z "${RESTIC_REPOSITORY:-}" ] || [ -z "${RESTIC_PASSWORD:-}" ]; then
  echo "Set RESTIC_REPOSITORY and RESTIC_PASSWORD environment variables before running." >&2
  exit 2
fi

# Initialize repo if needed
if restic snapshots >/dev/null 2>&1; then
  echo "Restic repo already initialized"
else
  echo "Initializing restic repo"
  restic init
fi

# Create a small test file and backup
testfile="/tmp/restic-test-$(date +%s).txt"
echo "hello restic $(date)" > "$testfile"
restic backup "$testfile"

# Get latest snapshot ID and restore to /tmp/restic-restore-test
snap=$(restic snapshots --short | tail -n1)
if [ -z "$snap" ]; then
  echo "No snapshot found after backup" >&2
  exit 3
fi

restore_dir="/tmp/restic-restore-$(date +%s)"
mkdir -p "$restore_dir"
restic restore "$snap" --target "$restore_dir"

echo "Restic backup and restore test completed. Restored files in: $restore_dir"
ls -l "$restore_dir"

exit 0
