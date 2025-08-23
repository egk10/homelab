#!/usr/bin/env bash
# mount_cephfs_example.sh
# Example script to mount CephFS and provide an fstab line. Run on the Docker host(s).

set -euo pipefail

MNT="/mnt/ceph"
MONS="eliedesk.velociraptor-scylla.ts.net:6789,minipcamd.velociraptor-scylla.ts.net:6789" # Use your Tailscale hostnames
CLIENT_NAME="client.admin"
SECRETFILE="/etc/ceph/ceph.client.admin.keyring" # or path to client keyring

if [ "$EUID" -ne 0 ]; then
  echo "Run as root to mount CephFS or use sudo"
  exit 1
fi

mkdir -p "$MNT"

echo "Mounting CephFS to $MNT (temporary)"
mount -t ceph "$MONS:/" "$MNT" -o name=$CLIENT_NAME,secretfile=$SECRETFILE,_netdev

echo "Mounted. Example fstab line (append to /etc/fstab):"
cat <<EOF
# CephFS mount
$MONS:/    $MNT    ceph    name=$CLIENT_NAME,secretfile=$SECRETFILE,_netdev    0 0
EOF

echo "If using kernel RBD for block devices, use 'rbd map' and then mkfs and mount. See the README for details."

exit 0
