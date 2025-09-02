#!/bin/bash
# verify_backups.sh - Verify backup integrity and test restoration
# Usage: ./scripts/verify_backups.sh

set -euo pipefail

# Load environment variables
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    . "$PROJECT_ROOT/.env"
    set +a
fi

# Configuration
VERIFY_DIR="/tmp/backup_verify_$(date +%s)"
LOG_FILE="$PROJECT_ROOT/logs/verify_$(date +%Y%m%d_%H%M%S).log"

# Restic configuration
export RESTIC_REPOSITORY="${RESTIC_REPOSITORY:-s3:http://100.90.57.27:80/homelab-backups}"
export RESTIC_PASSWORD="${RESTIC_PASSWORD:-CHANGE_THIS_STRONG_PASSWORD_FOR_RESTIC_ENCRYPTION}"
export AWS_ACCESS_KEY_ID="${BACKUP_S3_ACCESS_KEY_ID:-backup_user}"
export AWS_SECRET_ACCESS_KEY="${BACKUP_S3_SECRET_ACCESS_KEY:-dvUWnLW1K7SRKQI6XUibXFZMLNlPB_N7z_m99Q}"

# Logging function
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $*" | tee -a "$LOG_FILE"
}

# Create directories
mkdir -p "$VERIFY_DIR" "$(dirname "$LOG_FILE")"

log "🔍 Starting backup verification at $(date)"
log "📁 Verify directory: $VERIFY_DIR"
log "📝 Log file: $LOG_FILE"

# Check restic repository
if ! restic snapshots &>/dev/null; then
    log "❌ Cannot access restic repository: $RESTIC_REPOSITORY"
    exit 1
fi

log "✅ Restic repository accessible"

# Get latest snapshot
LATEST_SNAPSHOT=$(restic snapshots --json | jq -r '.[-1].id' 2>/dev/null || echo "")
if [ -z "$LATEST_SNAPSHOT" ]; then
    log "❌ No snapshots found in repository"
    exit 1
fi

log "📸 Latest snapshot: $LATEST_SNAPSHOT"

# Test restoration of a small file
log "🧪 Testing restoration..."

# Create test file in backup
TEST_FILE="$VERIFY_DIR/test_file.txt"
echo "Test file created at $(date)" > "$TEST_FILE"

# Backup test file
restic backup "$TEST_FILE" --tag "verification" --quiet

# Get test snapshot
TEST_SNAPSHOT=$(restic snapshots --tag "verification" --json | jq -r '.[-1].id' 2>/dev/null || echo "")

if [ -n "$TEST_SNAPSHOT" ]; then
    # Restore test file
    RESTORE_DIR="$VERIFY_DIR/restore_test"
    mkdir -p "$RESTORE_DIR"

    restic restore "$TEST_SNAPSHOT" --target "$RESTORE_DIR" --quiet

    if [ -f "$RESTORE_DIR/$(basename "$TEST_FILE")" ]; then
        log "✅ Restoration test passed"
    else
        log "❌ Restoration test failed"
    fi
else
    log "⚠️  Could not create test snapshot"
fi

# Check backup statistics
log "📊 Backup Statistics:"
restic stats | while read -r line; do
    log "   $line"
done

# Check snapshots by service
log "📋 Snapshots by service:"
for service in vaultwarden nextcloud immich homeassistant config docker; do
    count=$(restic snapshots --tag "$service" --json 2>/dev/null | jq -r 'length' 2>/dev/null || echo "0")
    if [ "$count" -gt 0 ]; then
        latest=$(restic snapshots --tag "$service" --json 2>/dev/null | jq -r '.[-1].time' 2>/dev/null || echo "unknown")
        log "   $service: $count snapshots (latest: $latest)"
    fi
done

# Check repository health
log "🏥 Repository Health Check:"
if restic check --read-data-subset 10% --quiet; then
    log "✅ Repository integrity check passed"
else
    log "❌ Repository integrity check failed"
fi

# Cleanup
rm -rf "$VERIFY_DIR"

log "🎉 Backup verification completed at $(date)"
log "📝 Full log available at: $LOG_FILE"

# Summary
echo ""
echo "=== VERIFICATION SUMMARY ==="
echo "✅ Repository accessible"
echo "✅ Latest snapshot: $LATEST_SNAPSHOT"
echo "📊 Check $LOG_FILE for detailed statistics"
echo "🧹 Cleanup completed"
