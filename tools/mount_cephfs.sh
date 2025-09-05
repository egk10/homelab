#!/bin/bash
# CephFS mount script for homelab
# Mount CephFS using local configuration

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Local Ceph configuration
CEPH_CONF="$PROJECT_ROOT/ceph.conf"
CEPH_KEYRING="$PROJECT_ROOT/ceph.client.admin.keyring"
MNT="/mnt/ceph"

echo "🔧 CephFS Mount Script"
echo "===================="
echo "Config: $CEPH_CONF"
echo "Keyring: $CEPH_KEYRING"
echo "Mount point: $MNT"

# Check if files exist
if [ ! -f "$CEPH_CONF" ]; then
    echo "❌ Ceph config not found: $CEPH_CONF"
    exit 1
fi

if [ ! -f "$CEPH_KEYRING" ]; then
    echo "❌ Ceph keyring not found: $CEPH_KEYRING"
    exit 1
fi

# Create mount point
sudo mkdir -p "$MNT"

# Check if already mounted
if mountpoint -q "$MNT"; then
    echo "✅ CephFS already mounted at $MNT"
    df -h "$MNT"
    exit 0
fi

# Mount CephFS using ceph-fuse
echo "🔄 Mounting CephFS with ceph-fuse..."
# ceph-fuse uses -c (conf) and -k (keyring); remove unsupported --client-mounts
sudo ceph-fuse "$MNT" \
    -c "$CEPH_CONF" \
    -k "$CEPH_KEYRING"

# Check if mount was successful
if mountpoint -q "$MNT"; then
    echo "✅ CephFS mounted successfully at $MNT"
    df -h "$MNT"
    
    # Create required subdirectories
    echo "📂 Creating required subdirectories..."
    sudo mkdir -p "$MNT/nextcloud" "$MNT/vaultwarden" "$MNT/immich"
    sudo chown egk:egk "$MNT/nextcloud" "$MNT/vaultwarden" "$MNT/immich" 2>/dev/null || true
    
    echo "✅ CephFS setup complete!"
else
    echo "❌ Failed to mount CephFS"
    exit 1
fi
