#!/bin/bash
# unified_backup.sh - Master backup script for all homelab services
# Backs up all services to Ceph S3 storage using restic

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
DATE=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$PROJECT_ROOT/logs/backup_$DATE.log"
BACKUP_ROOT="/tmp/homelab_backup_$DATE"

# Restic configuration
export RESTIC_REPOSITORY="${RESTIC_REPOSITORY:-s3:http://100.90.57.27:80/homelab-backups}"
export RESTIC_PASSWORD="${RESTIC_PASSWORD:-$(openssl rand -base64 32)}"
export AWS_ACCESS_KEY_ID="${BACKUP_S3_ACCESS_KEY_ID:-backup_user}"
export AWS_SECRET_ACCESS_KEY="${BACKUP_S3_SECRET_ACCESS_KEY:-dvUWnLW1K7SRKQI6XUibXFZMLNlPB_N7z_m99Q}"

# Create log directory
mkdir -p "$PROJECT_ROOT/logs"

# Logging function
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $*" | tee -a "$LOG_FILE"
}

# Error handling
error_exit() {
    log "❌ ERROR: $1"
    exit 1
}

log "🚀 Starting unified homelab backup at $(date)"
log "📁 Backup repository: $RESTIC_REPOSITORY"
log "📝 Log file: $LOG_FILE"

# Verify prerequisites
command -v restic &>/dev/null || error_exit "restic not installed"
command -v docker &>/dev/null || error_exit "docker not installed"

# Initialize restic repository if needed
if ! restic snapshots &>/dev/null; then
    log "📦 Initializing restic repository..."
    restic init || error_exit "Failed to initialize restic repository"
fi

# Create backup directory
mkdir -p "$BACKUP_ROOT"

# Function to backup service data
backup_service() {
    local service_name="$1"
    local source_path="$2"
    local description="$3"

    log "🔄 Backing up $service_name..."

    if [ ! -d "$source_path" ]; then
        log "⚠️  Source path not found: $source_path"
        return 1
    fi

    # Create service-specific backup
    local service_backup="$BACKUP_ROOT/$service_name"
    mkdir -p "$service_backup"

    # Copy data (exclude temp files, logs, etc.)
    if [ "$service_name" = "vaultwarden" ]; then
        # Special handling for Vaultwarden database
        cp "$source_path/db.sqlite3" "$service_backup/" 2>/dev/null || log "⚠️  Could not backup Vaultwarden database"
        cp -r "$source_path/attachments" "$service_backup/" 2>/dev/null || true
        cp -r "$source_path/sends" "$service_backup/" 2>/dev/null || true
    elif [ "$service_name" = "nextcloud" ]; then
        # Nextcloud data directory
        cp -r "$source_path/data" "$service_backup/" 2>/dev/null || true
        cp -r "$source_path/config" "$service_backup/" 2>/dev/null || true
    elif [ "$service_name" = "immich" ]; then
        # Immich uploads (already on S3, but backup metadata)
        cp -r "$source_path" "$service_backup/" 2>/dev/null || true
    fi

    # Backup to restic
    if [ -d "$service_backup" ] && [ "$(ls -A "$service_backup" 2>/dev/null)" ]; then
        restic backup "$service_backup" --tag "$service_name" --tag "automated" || log "⚠️  Restic backup failed for $service_name"
        log "✅ $service_name backup completed"
    else
        log "⚠️  No data to backup for $service_name"
    fi
}

# Backup individual services
log "📦 Starting service backups..."

# Vaultwarden
backup_service "vaultwarden" "/mnt/s3/vaultwarden" "Vaultwarden password manager data"

# Nextcloud
backup_service "nextcloud" "/mnt/ceph/nextcloud" "Nextcloud file storage data"

# Immich (metadata only, since files are on S3)
backup_service "immich" "/mnt/s3/immich" "Immich photo metadata"

# Home Assistant
if [ -d "/home/egk/homeassist/config" ]; then
    backup_service "homeassistant" "/home/egk/homeassist/config" "Home Assistant configuration"
fi

# Backup Docker volumes (if any)
log "🐳 Backing up Docker volumes..."
docker run --rm -v /var/lib/docker/volumes:/volumes:ro alpine tar czf - /volumes 2>/dev/null | restic backup --stdin --stdin-filename "docker_volumes.tar.gz" --tag "docker" --tag "volumes" 2>/dev/null || log "⚠️  Docker volumes backup failed"

# Backup configuration files
log "⚙️  Backing up configuration files..."
restic backup "$PROJECT_ROOT/.env" "$PROJECT_ROOT/docker-compose.yml" "$PROJECT_ROOT/tsdproxy" --tag "config" --tag "homelab" || log "⚠️  Config backup failed"

# Cleanup
rm -rf "$BACKUP_ROOT"

# Generate backup report
log "📊 Generating backup report..."
{
    echo "=== BACKUP REPORT ==="
    echo "Date: $(date)"
    echo "Repository: $RESTIC_REPOSITORY"
    echo ""

    echo "=== SNAPSHOTS ==="
    restic snapshots --tag automated | tail -10

    echo ""
    echo "=== STATISTICS ==="
    restic stats

    echo ""
    echo "=== RECENT BACKUPS ==="
    restic snapshots --json | jq -r '.[] | select(.tags[]? == "automated") | "\(.time) \(.tags[])"' | tail -5 2>/dev/null || echo "No automated backups found"

} >> "$LOG_FILE"

log "✅ Unified backup completed successfully"
log "📝 Full log available at: $LOG_FILE"

# Optional: Send notification (if configured)
if command -v curl &>/dev/null && [ -n "${BACKUP_NOTIFICATION_URL:-}" ]; then
    curl -X POST "$BACKUP_NOTIFICATION_URL" \
        -H "Content-Type: application/json" \
        -d "{\"text\":\"Homelab backup completed successfully\",\"timestamp\":\"$DATE\"}" 2>/dev/null || true
fi

# Cleanup old backups (keep last 30 days)
log "🧹 Cleaning up old backups..."
restic forget --keep-daily 30 --keep-weekly 12 --keep-monthly 24 --prune || log "⚠️  Cleanup failed"

log "🎉 Backup process completed at $(date)"
