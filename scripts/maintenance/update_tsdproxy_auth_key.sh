#!/bin/bash
# Script to update tsdproxy with a new reusable Tailscale auth key

set -e

echo "=== Update tsdproxy Tailscale Auth Key ==="
echo
echo "1. Go to https://login.tailscale.com/admin/settings/keys"
echo "2. Click 'Generate new key'"
echo "3. Set it to 'Reusable' and choose expiry (or no expiry)"
echo "4. Copy the generated key (starts with tskey-)"
echo
echo -n "Enter your new reusable auth key: "
read -r NEW_KEY

if [[ ! "$NEW_KEY" =~ ^tskey- ]]; then
    echo "Error: Key should start with 'tskey-'"
    exit 1
fi

# Update the auth key file
printf '%s\n' "$NEW_KEY" > tsdproxy/config/authkey
chmod 600 tsdproxy/config/authkey

echo "Auth key updated in tsdproxy/config/authkey"

# Clear old state
echo "Clearing old tsdproxy state..."
sudo rm -rf tsdproxy/datadir/default/*

# Restart tsdproxy
echo "Restarting tsdproxy..."
docker compose up -d --no-deps --force-recreate tsdproxy

echo "Waiting for tsdproxy to start..."
sleep 5

echo "=== tsdproxy logs ==="
docker logs --tail 50 tsdproxy

echo
echo "=== tsdproxy status ==="
docker ps --filter name=tsdproxy --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'

echo
echo "If you see 'invalid key' errors above, the key may not be reusable."
echo "If you see successful Tailscale login, try accessing:"
echo "  https://vaultwarden.velociraptor-scylla.ts.net"
echo "  https://nextcloud.velociraptor-scylla.ts.net"
echo "  https://immich.velociraptor-scylla.ts.net"
