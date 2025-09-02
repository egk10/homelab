#!/bin/bash
# setup_backup_system.sh - Setup automated backup system for homelab
# Usage: ./scripts/setup_backup_system.sh

set -euo pipefail

# Load environment variables
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    . "$PROJECT_ROOT/.env"
    set +a
fi

echo "🔧 Setting up Homelab Backup System"
echo "==================================="

# Check prerequisites
echo "📋 Checking prerequisites..."

if ! command -v restic &>/dev/null; then
    echo "❌ restic not installed. Installing..."
    sudo apt update && sudo apt install -y restic
fi

if ! command -v jq &>/dev/null; then
    echo "❌ jq not installed. Installing..."
    sudo apt update && sudo apt install -y jq
fi

if ! command -v aws &>/dev/null && ! command -v s3cmd &>/dev/null; then
    echo "⚠️  Neither awscli nor s3cmd found. Installing awscli..."
    sudo apt update && sudo apt install -y awscli
fi

echo "✅ Prerequisites OK"

# Create necessary directories
echo "📁 Creating directories..."
mkdir -p "$PROJECT_ROOT/logs"
mkdir -p "$PROJECT_ROOT/backups"

# Setup systemd services
echo "⚙️  Setting up systemd services..."

# Copy service files to systemd directory
sudo cp "$PROJECT_ROOT/homelab-backup.service" /etc/systemd/system/
sudo cp "$PROJECT_ROOT/homelab-backup.timer" /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable and start timer
sudo systemctl enable homelab-backup.timer
sudo systemctl start homelab-backup.timer

echo "✅ Systemd services configured"

# Initialize restic repository
echo "📦 Initializing restic repository..."

export RESTIC_REPOSITORY="${RESTIC_REPOSITORY:-s3:http://100.90.57.27:80/homelab-backups}"
export RESTIC_PASSWORD="${RESTIC_PASSWORD:-CHANGE_THIS_STRONG_PASSWORD_FOR_RESTIC_ENCRYPTION}"
export AWS_ACCESS_KEY_ID="${BACKUP_S3_ACCESS_KEY_ID:-backup_user}"
export AWS_SECRET_ACCESS_KEY="${BACKUP_S3_SECRET_ACCESS_KEY:-dvUWnLW1K7SRKQI6XUibXFZMLNlPB_N7z_m99Q}"

if [ "$RESTIC_PASSWORD" = "CHANGE_THIS_STRONG_PASSWORD_FOR_RESTIC_ENCRYPTION" ]; then
    echo "⚠️  WARNING: Using default RESTIC_PASSWORD. Please change it in .env file!"
    echo "   Generate a strong password with: openssl rand -base64 32"
fi

if ! restic snapshots &>/dev/null; then
    echo "Creating new restic repository..."
    restic init
    echo "✅ Restic repository initialized"
else
    echo "✅ Restic repository already exists"
fi

# Test backup system
echo "🧪 Testing backup system..."
"$SCRIPT_DIR/unified_backup.sh" || {
    echo "❌ Initial backup failed. Check configuration."
    exit 1
}

# Test verification
echo "🔍 Testing backup verification..."
"$SCRIPT_DIR/verify_backups.sh" || {
    echo "❌ Backup verification failed."
    exit 1
}

# Create cron job as fallback
echo "⏰ Setting up cron fallback..."
CRON_JOB="0 2 * * * /home/egk/homelab/scripts/unified_backup.sh"
if ! crontab -l 2>/dev/null | grep -q "unified_backup.sh"; then
    (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
    echo "✅ Cron job added as fallback"
else
    echo "✅ Cron job already exists"
fi

echo ""
echo "🎉 Backup system setup completed!"
echo ""
echo "=== CONFIGURATION SUMMARY ==="
echo "📦 Restic Repository: $RESTIC_REPOSITORY"
echo "⏰ Daily Backup: Enabled (systemd timer + cron fallback)"
echo "📁 Logs: $PROJECT_ROOT/logs/"
echo "🔍 Verification: Run ./scripts/verify_backups.sh"
echo ""
echo "=== NEXT STEPS ==="
echo "1. Change RESTIC_PASSWORD in .env file if using default"
echo "2. Test manual backup: ./scripts/unified_backup.sh"
echo "3. Monitor logs: tail -f $PROJECT_ROOT/logs/backup_*.log"
echo "4. Check timer status: systemctl status homelab-backup.timer"
echo ""
echo "=== MANUAL BACKUP COMMANDS ==="
echo "• All services: ./scripts/unified_backup.sh"
echo "• Vaultwarden only: ./scripts/backup_vaultwarden.sh"
echo "• Verify backups: ./scripts/verify_backups.sh"
