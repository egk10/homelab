#!/bin/bash
# vaultwarden_recovery.sh - Fix Vaultwarden database corruption after reboot
# Usage: ./scripts/vaultwarden_recovery.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "🔧 Vaultwarden Database Recovery Script"
echo "======================================"

cd "$PROJECT_ROOT"

# Check if Vaultwarden is running and healthy
if docker compose ps vaultwarden | grep -q "healthy"; then
    echo "✅ Vaultwarden is already running and healthy"
    exit 0
fi

echo "⚠️  Vaultwarden appears to have issues, checking logs..."

# Check recent logs for database errors
if docker compose logs vaultwarden --tail=20 2>/dev/null | grep -q "database disk image is malformed"; then
    echo "🔍 Database corruption detected, attempting recovery..."

    # Stop the container
    echo "1. Stopping Vaultwarden container..."
    docker compose stop vaultwarden

    # Backup corrupted database
    CORRUPTED_BACKUP="/mnt/s3/vaultwarden/db.sqlite3.corrupted.$(date +%Y%m%d_%H%M%S)"
    echo "2. Backing up corrupted database to: $CORRUPTED_BACKUP"
    cp /mnt/s3/vaultwarden/db.sqlite3 "$CORRUPTED_BACKUP" 2>/dev/null || echo "   Warning: Could not backup corrupted database"

    # Find the most recent backup
    LATEST_BACKUP=$(ls -t /mnt/s3/vaultwarden/db_*.sqlite3 2>/dev/null | head -1)

    if [ -n "$LATEST_BACKUP" ] && [ -f "$LATEST_BACKUP" ]; then
        echo "3. Restoring from backup: $LATEST_BACKUP"
        cp "$LATEST_BACKUP" /mnt/s3/vaultwarden/db.sqlite3

        # Start the container
        echo "4. Starting Vaultwarden..."
        docker compose start vaultwarden

        # Wait a moment and check status
        sleep 5
        if docker compose ps vaultwarden | grep -q "healthy"; then
            echo "✅ Vaultwarden recovery successful!"
            echo "   Corrupted database backed up to: $CORRUPTED_BACKUP"
            echo "   Restored from: $LATEST_BACKUP"
        else
            echo "❌ Recovery failed, check logs:"
            docker compose logs vaultwarden --tail=10
        fi
    else
        echo "❌ No backup database found!"
        echo "   Available files in /mnt/s3/vaultwarden/:"
        ls -la /mnt/s3/vaultwarden/db*.sqlite3 2>/dev/null || echo "   No database files found"
        echo ""
        echo "   Manual intervention required. You may need to:"
        echo "   - Restore from a different backup"
        echo "   - Reinitialize the database (will lose data)"
        echo "   - Check S3FS mount permissions"
    fi
else
    echo "🔍 No database corruption detected, checking other issues..."

    # Try restarting the container
    echo "Attempting container restart..."
    docker compose restart vaultwarden

    sleep 5
    if docker compose ps vaultwarden | grep -q "healthy"; then
        echo "✅ Vaultwarden restarted successfully"
    else
        echo "❌ Restart failed, check logs:"
        docker compose logs vaultwarden --tail=10
    fi
fi

echo ""
echo "📋 Recovery script completed at $(date)"
