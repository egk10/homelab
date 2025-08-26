#!/bin/bash
# Simple S3FS Mount Verification Script
# Prevents Docker Compose from starting if S3FS mounts are not available
# This prevents local storage fallback without aggressive monitoring

set -e

MOUNT_SERVICES=(
    "s3fs-nextcloud-data.service:/mnt/s3fs/nextcloud-data"
    "s3fs-immich.service:/mnt/s3fs/immich"
    "s3fs-vaultwarden.service:/mnt/s3/vaultwarden"
)

echo "🔍 Verifying S3FS mounts before starting containers..."

for service_mount in "${MOUNT_SERVICES[@]}"; do
    service_name="${service_mount%:*}"
    mount_point="${service_mount#*:}"
    
    # Check if service is active
    if ! systemctl is-active --quiet "$service_name"; then
        echo "❌ CRITICAL: S3FS service $service_name is not active"
        echo "   Please start the service: sudo systemctl start $service_name"
        exit 1
    fi
    
    # Check if mount point is actually mounted
    if ! mountpoint -q "$mount_point"; then
        echo "❌ CRITICAL: S3FS mount $mount_point is not mounted"
        echo "   Service $service_name is running but mount failed"
        exit 1
    fi
    
    echo "✅ S3FS mount $mount_point is healthy (via $service_name)"
done

echo "🟢 All S3FS mounts verified - safe to start containers"
