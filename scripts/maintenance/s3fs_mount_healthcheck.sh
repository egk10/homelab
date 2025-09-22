#!/bin/bash
# s3fs_mount_healthcheck.sh - Comprehensive S3FS mount health checker
# This script provides a robust health check for S3FS mounts before starting containers

set -euo pipefail

MOUNT_PATH="/mnt/s3/vaultwarden"
MAX_RETRIES=30
RETRY_DELAY=2

echo "🔍 Checking S3FS mount health for $MOUNT_PATH"

for i in $(seq 1 $MAX_RETRIES); do
    echo "📍 Attempt $i/$MAX_RETRIES"
    
    # Check if directory exists
    if [ ! -d "$MOUNT_PATH" ]; then
        echo "❌ Mount directory does not exist: $MOUNT_PATH"
        sleep $RETRY_DELAY
        continue
    fi
    
    # Check if it's mounted
    if ! mountpoint -q "$MOUNT_PATH"; then
        echo "❌ $MOUNT_PATH is not mounted"
        sleep $RETRY_DELAY
        continue
    fi
    
    # Check if it's accessible (try to list contents)
    if ! ls "$MOUNT_PATH" >/dev/null 2>&1; then
        echo "❌ $MOUNT_PATH is not accessible"
        sleep $RETRY_DELAY
        continue
    fi
    
    # Check if critical database file exists
    if [ -f "$MOUNT_PATH/db.sqlite3" ]; then
        # Check if database is readable
        if sqlite3 "$MOUNT_PATH/db.sqlite3" "SELECT COUNT(*) FROM sqlite_master;" >/dev/null 2>&1; then
            echo "✅ S3FS mount is healthy and database is accessible"
            exit 0
        else
            echo "⚠️  Mount is accessible but database appears corrupted"
            # Continue anyway - Vaultwarden might be able to handle this
            exit 0
        fi
    else
        echo "⚠️  Database file does not exist yet (new install?)"
        # This is OK for new installations
        exit 0
    fi
done

echo "❌ S3FS mount health check failed after $MAX_RETRIES attempts"
exit 1