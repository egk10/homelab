#!/bin/bash
# Test script for Tailscale domain access
# Tests all homelab services via their Tailscale domains

echo "🌐 Testing Tailscale Domain Access..."
echo "======================================"

services=(
    "nextcloud.your-tailscale-domain.ts.net"
    "immich.your-tailscale-domain.ts.net" 
    "vaultwarden.your-tailscale-domain.ts.net"
    "homeassistant.your-tailscale-domain.ts.net"
)

for service in "${services[@]}"; do
    echo -n "Testing $service... "
    
    response=$(curl -s -L -w "%{http_code}" -o /dev/null --max-time 10 "https://$service" 2>/dev/null)
    
    if [[ $response =~ ^[23] ]]; then
        echo "✅ $response"
    else
        echo "❌ $response"
    fi
    
    sleep 1
done

echo ""
echo "🔍 Testing service-specific endpoints..."
echo "========================================"

# Test Nextcloud status
echo -n "Nextcloud status endpoint... "
response=$(curl -s -L -w "%{http_code}" -o /dev/null --max-time 10 "https://nextcloud.your-tailscale-domain.ts.net/status.php" 2>/dev/null)
echo "$response"

# Test Immich API
echo -n "Immich API endpoint... "
response=$(curl -s -L -w "%{http_code}" -o /dev/null --max-time 10 "https://immich.your-tailscale-domain.ts.net/api/server-info/ping" 2>/dev/null)
echo "$response"

echo ""
echo "✅ Tailscale domain testing completed!"
