#!/bin/bash
# check_s3fs_mount.sh - Check if S3FS mount is ready and accessible
# This script is used by Docker health checks to ensure mounts are ready

set -euo pipefail

MOUNT_PATH="$1"
TEST_FILE="${MOUNT_PATH}/.mount_test"

# Check if directory is mounted
if ! mountpoint -q "$MOUNT_PATH"; then
    echo "❌ $MOUNT_PATH is not mounted"
    exit 1
fi

# Check if mount is writable by trying to create a test file
if ! touch "$TEST_FILE" 2>/dev/null; then
    echo "❌ $MOUNT_PATH is not writable"
    exit 1
fi

# Clean up test file
rm -f "$TEST_FILE" 2>/dev/null || true

echo "✅ $MOUNT_PATH is mounted and accessible"
exit 0