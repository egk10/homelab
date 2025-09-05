#!/bin/bash
# S3FS Auto-Mount Script for Homelab
# This script ensures S3FS mounts are available before starting Docker services

NEXTCLOUD_MOUNT="/mnt/s3/nextcloud"
VAULTWARDEN_MOUNT="/mnt/s3/vaultwarden"
CEPH_RGW_URL="http://100.90.57.27:80"
PASSWD_FILE="/etc/passwd-s3fs"

check_mount() {
    local mount_point=$1
    mountpoint -q "$mount_point"
}

mount_s3fs() {
    local bucket=$1
    local mount_point=$2
    local uid=$3
    local gid=$4
    
    echo "Mounting $bucket to $mount_point..."
    
    # Create mount point if it doesn't exist
    mkdir -p "$mount_point"
    
    # Mount with S3FS
    s3fs "$bucket" "$mount_point" \
        -o passwd_file="$PASSWD_FILE" \
        -o url="$CEPH_RGW_URL" \
        -o use_path_request_style \
        -o uid="$uid" \
        -o gid="$gid" \
        -o allow_other \
        -o nonempty
    
    if check_mount "$mount_point"; then
        echo "✅ Successfully mounted $bucket to $mount_point"
        return 0
    else
        echo "❌ Failed to mount $bucket to $mount_point"
        return 1
    fi
}

echo "🔧 Checking S3FS mounts for homelab services..."

# Check and mount Nextcloud
if ! check_mount "$NEXTCLOUD_MOUNT"; then
    mount_s3fs "nextcloud-data" "$NEXTCLOUD_MOUNT" "33" "33"
else
    echo "✅ Nextcloud S3FS already mounted"
fi

# Check and mount Vaultwarden
if ! check_mount "$VAULTWARDEN_MOUNT"; then
    mount_s3fs "backup-vaultwarden" "$VAULTWARDEN_MOUNT" "1000" "1000"
else
    echo "✅ Vaultwarden S3FS already mounted"
fi

echo "🎉 S3FS mount check completed!"
