#!/usr/bin/env bash
# post_reboot_recovery.sh - Complete post-reboot recovery and troubleshooting
# Usage: ./scripts/post_reboot_recovery.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "🔧 POST-REBOOT RECOVERY SCRIPT"
echo "=============================="
echo "Timestamp: $(date)"
echo "Working directory: $PROJECT_ROOT"
echo ""

# Step 1: Mount CephFS if not mounted
echo "📁 STEP 1: Checking CephFS mount..."
if ! mountpoint -q /mnt/ceph; then
    echo "⚠️  CephFS not mounted at /mnt/ceph"
    echo "🔄 Attempting to mount CephFS..."
    
    # Check if mount script exists
    if [ -f "$PROJECT_ROOT/scripts/mount_cephfs_example.sh" ]; then
        echo "Found mount script, executing..."
        sudo "$PROJECT_ROOT/scripts/mount_cephfs_example.sh" || echo "❌ Mount script failed"
    else
        echo "🔧 Manual CephFS mount required. Please run:"
        echo "sudo ceph-fuse /mnt/ceph --client-mounts --keyfile=$PROJECT_ROOT/ceph.client.admin.keyring --conf=$PROJECT_ROOT/ceph.conf"
    fi
else
    echo "✅ CephFS is already mounted"
fi

# Step 2: Create missing directories
echo ""
echo "📂 STEP 2: Creating missing directories..."
REQUIRED_DIRS=(
    "/mnt/ceph/nextcloud"
    "/mnt/ceph/vaultwarden" 
    "/mnt/ceph/immich"
    "/home/egk/homeassist/config"
)

for dir in "${REQUIRED_DIRS[@]}"; do
    if [ ! -d "$dir" ]; then
        echo "🔄 Creating directory: $dir"
        sudo mkdir -p "$dir"
        sudo chown egk:egk "$dir" 2>/dev/null || true
    else
        echo "✅ Directory exists: $dir"
    fi
done

# Step 3: Check and restart S3FS services
echo ""
echo "🗄️  STEP 3: Checking S3FS services..."
S3FS_SERVICES=(
    "s3fs-immich.service"
    "s3fs-nextcloud-data.service"
    "s3fs-vaultwarden.service"
)

for service in "${S3FS_SERVICES[@]}"; do
    echo "Checking $service..."
    if systemctl is-active --quiet "$service"; then
        echo "✅ $service is running"
    else
        echo "⚠️  $service is not running, attempting restart..."
        sudo systemctl restart "$service" || echo "❌ Failed to restart $service"
    fi
done

# Step 4: Verify S3FS mounts
echo ""
echo "🔍 STEP 4: Verifying S3FS mounts..."
echo "Current S3FS mounts:"
mount | grep s3fs || echo "No S3FS mounts found"

# Step 5: Check Docker services
echo ""
echo "🐳 STEP 5: Checking Docker services..."
cd "$PROJECT_ROOT"

# Check if Immich is missing
if ! docker ps --format "table {{.Names}}" | grep -q immich; then
    echo "⚠️  Immich containers not found"
    echo "🔄 Starting missing services..."
    docker compose up -d
else
    echo "✅ Docker services appear to be running"
fi

# Step 5.5: Check Vaultwarden database health
echo ""
echo "🔐 STEP 5.5: Checking Vaultwarden database health..."
if [ -f "$PROJECT_ROOT/scripts/vaultwarden_recovery.sh" ]; then
    echo "Running Vaultwarden recovery check..."
    "$PROJECT_ROOT/scripts/vaultwarden_recovery.sh" || echo "⚠️  Vaultwarden recovery completed with warnings"
fi

# Step 6: Run comprehensive checks
echo ""
echo "🔍 STEP 6: Running comprehensive system checks..."

# Run preflight checks
if [ -f "$PROJECT_ROOT/scripts/preflight_checks.sh" ]; then
    echo "Running preflight checks..."
    "$PROJECT_ROOT/scripts/preflight_checks.sh" || echo "⚠️  Preflight checks detected issues"
fi

# Test Tailscale domains
if [ -f "$PROJECT_ROOT/test_tailscale_domains.sh" ]; then
    echo "Testing Tailscale domain access..."
    "$PROJECT_ROOT/test_tailscale_domains.sh" || echo "⚠️  Some services may not be accessible"
fi

# Step 7: Summary and recommendations
echo ""
echo "📋 STEP 7: Recovery Summary"
echo "=========================="
echo "✅ CephFS mount: $(mountpoint -q /mnt/ceph && echo "OK" || echo "FAILED")"
echo "✅ S3FS mounts: $(mount | grep -c s3fs || echo "0") active"
echo "✅ Docker containers: $(docker ps --format "table {{.Names}}" | wc -l) running"

echo ""
echo "🎯 RECOMMENDATIONS:"
echo "1. If services are still not accessible, check firewall/Tailscale connectivity"
echo "2. Monitor logs: docker compose logs -f"
echo "3. For persistent issues, run: ./scripts/preflight_checks.sh"
echo ""
echo "🔧 Recovery script completed at $(date)"
