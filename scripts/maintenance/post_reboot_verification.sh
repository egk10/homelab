#!/bin/bash
# post_reboot_verification.sh - Verify all critical services after reboot
# This script helps identify issues early after system restart

set -euo pipefail

echo "🚀 Post-reboot verification starting..."
echo "📅 System uptime: $(uptime -p)"
echo "📅 Boot time: $(uptime -s)"
echo ""

# Check S3FS mounts
echo "🔍 Checking S3FS mounts..."
for mount_path in "/mnt/s3/vaultwarden" "/mnt/s3fs/nextcloud-data" "/mnt/s3fs/immich"; do
    if mountpoint -q "$mount_path"; then
        echo "✅ $mount_path is mounted"
        
        # Check accessibility
        if ls "$mount_path" >/dev/null 2>&1; then
            echo "✅ $mount_path is accessible"
        else
            echo "❌ $mount_path is mounted but not accessible"
        fi
    else
        echo "❌ $mount_path is NOT mounted"
    fi
done
echo ""

# Check Docker containers
echo "🐳 Checking Docker containers..."
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "(vaultwarden|nextcloud|immich)" || echo "❌ No critical containers running"
echo ""

# Check Vaultwarden database specifically
echo "🔒 Checking Vaultwarden database..."
if [ -f "/mnt/s3/vaultwarden/db.sqlite3" ]; then
    DB_SIZE=$(stat -c%s "/mnt/s3/vaultwarden/db.sqlite3")
    USER_COUNT=$(sqlite3 /mnt/s3/vaultwarden/db.sqlite3 "SELECT COUNT(*) FROM users;" 2>/dev/null || echo "ERROR")
    
    echo "📊 Database size: $DB_SIZE bytes"
    echo "👥 User count: $USER_COUNT"
    
    if [ "$USER_COUNT" == "0" ]; then
        echo "❌ CRITICAL: Vaultwarden database has no users! Data loss detected!"
        echo "🔧 Consider restoring from backup using:"
        echo "   cd /home/egk/homelab && scripts/backup/restore_vaultwarden.sh"
    elif [ "$USER_COUNT" == "ERROR" ]; then
        echo "❌ CRITICAL: Vaultwarden database is corrupted!"
    else
        echo "✅ Vaultwarden database looks healthy"
    fi
else
    echo "❌ CRITICAL: Vaultwarden database file not found!"
fi
echo ""

# Check for recent backup
echo "💾 Checking recent backups..."
LATEST_BACKUP=$(ls -t /home/egk/homelab/logs/backup_*.log 2>/dev/null | head -1 || echo "")
if [ -n "$LATEST_BACKUP" ]; then
    echo "📁 Latest backup log: $(basename "$LATEST_BACKUP")"
    echo "📅 Backup date: $(stat -c %y "$LATEST_BACKUP" | cut -d' ' -f1)"
else
    echo "⚠️  No backup logs found"
fi

echo ""
echo "🎉 Post-reboot verification completed"