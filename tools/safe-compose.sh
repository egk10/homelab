#!/bin/bash
# Safe Docker Compose wrapper that verifies S3FS mounts first
# Prevents accidental local storage fallback

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# Verify S3FS mounts before starting
if ! ./scripts/maintenance/verify_s3fs_mounts.sh; then
    echo ""
    echo "🚫 STOPPING: S3FS mounts not ready"
    echo "   This prevents containers from falling back to local storage"
    echo "   Please fix S3FS issues before starting containers"
    exit 1
fi

echo ""
echo "🚀 S3FS verification passed - starting containers..."
docker compose "$@"
