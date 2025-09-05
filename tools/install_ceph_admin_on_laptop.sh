#!/usr/bin/env bash
# install_ceph_admin_on_laptop.sh
# Usage: run this on the laptop as root (sudo ./install_ceph_admin_on_laptop.sh)
set -euo pipefail

# Move copied ceph files from ~/homelab into /etc/ceph and install ceph-common
apt update
apt install -y ceph-common
mkdir -p /etc/ceph
if [ -f "$HOME/homelab/ceph.conf" ]; then
  mv "$HOME/homelab/ceph.conf" /etc/ceph/ceph.conf
fi
if [ -f "$HOME/homelab/ceph.client.admin.keyring" ]; then
  mv "$HOME/homelab/ceph.client.admin.keyring" /etc/ceph/ceph.client.admin.keyring
  chown root:root /etc/ceph/ceph.client.admin.keyring
  chmod 600 /etc/ceph/ceph.client.admin.keyring
fi
if [ -f "/etc/ceph/ceph.conf" ]; then
  chown root:root /etc/ceph/ceph.conf || true
  chmod 644 /etc/ceph/ceph.conf || true
fi

# Print status
ceph -s || true

echo "Ceph admin files moved and ceph-common installed. If ceph -s failed, check /etc/ceph/ceph.client.admin.keyring and network connectivity to cluster."
