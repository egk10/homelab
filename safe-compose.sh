#!/bin/bash
# Safe Docker Compose wrapper that verifies S3FS mounts first
# Prevents accidental local storage fallback

cd "$(dirname "$0")"

# Verify S3FS mounts before starting
if ! ./scripts/verify_s3fs_mounts.sh; then
    echo ""
    echo "🚫 STOPPING: S3FS mounts not ready"
    echo "   This prevents containers from falling back to local storage"
    echo "   Please fix S3FS issues before starting containers"
    exit 1
fi

echo ""
echo "🚀 S3FS verification passed - starting containers..."
docker compose "$@"
