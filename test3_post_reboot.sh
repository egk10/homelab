#!/bin/bash
# Test 3: Post-Reboot Full System Verification
# Run this script after server reboot to verify everything works

echo "🔄 POST-REBOOT SYSTEM VERIFICATION"
echo "=================================="
echo "Started at: $(date)"
echo ""

# Function to test HTTP response
test_http() {
    local url=$1
    local name=$2
    echo -n "Testing $name... "
    response=$(curl -s -w "%{http_code}" -o /dev/null --max-time 15 "$url" 2>/dev/null)
    if [[ $response =~ ^[23] ]]; then
        echo "✅ $response"
        return 0
    else
        echo "❌ $response"
        return 1
    fi
}

echo "1️⃣ CHECKING S3FS MOUNTS"
echo "----------------------"
mounts=(
    "s3fs-nextcloud-data.service:/mnt/s3fs/nextcloud-data"
    "s3fs-immich.service:/mnt/s3fs/immich"
    "s3fs-vaultwarden.service:/mnt/s3/vaultwarden"
)

all_mounts_ok=true
for service_mount in "${mounts[@]}"; do
    service_name="${service_mount%:*}"
    mount_point="${service_mount#*:}"
    
    echo -n "  $service_name... "
    if systemctl is-active --quiet "$service_name" && mountpoint -q "$mount_point"; then
        echo "✅ Active & Mounted"
    else
        echo "❌ Failed"
        all_mounts_ok=false
    fi
done

echo ""
echo "2️⃣ STARTING CONTAINERS SAFELY"
echo "-----------------------------"
if [ "$all_mounts_ok" = true ]; then
    echo "S3FS mounts verified - starting containers..."
    cd /home/egk/homelab
    ./safe-compose.sh up -d
    echo "Waiting 60 seconds for services to initialize..."
    sleep 60
else
    echo "❌ S3FS mounts failed - NOT starting containers"
    exit 1
fi

echo ""
echo "3️⃣ TESTING LOCAL ACCESS"
echo "----------------------"
test_http "http://localhost:8081" "Nextcloud (local)"
test_http "http://localhost:2283" "Immich (local)"
test_http "http://localhost:8083" "Vaultwarden (local)"
test_http "http://localhost:8123" "Home Assistant (local)"

echo ""
echo "4️⃣ TESTING TAILSCALE DOMAINS"
echo "----------------------------"
test_http "https://nextcloud.velociraptor-scylla.ts.net" "Nextcloud (Tailscale)"
test_http "https://immich.velociraptor-scylla.ts.net" "Immich (Tailscale)"
test_http "https://vaultwarden.velociraptor-scylla.ts.net" "Vaultwarden (Tailscale)"
test_http "https://homeassistant.velociraptor-scylla.ts.net" "Home Assistant (Tailscale)"

echo ""
echo "5️⃣ VERIFYING DATA PERSISTENCE"
echo "-----------------------------"
echo -n "Nextcloud files: "
if [ -d "/mnt/s3fs/nextcloud-data/admin" ]; then
    file_count=$(sudo find /mnt/s3fs/nextcloud-data -type f 2>/dev/null | wc -l)
    echo "✅ $file_count files found"
else
    echo "❌ No user data found"
fi

echo -n "Immich data: "
if [ -d "/mnt/s3fs/immich" ]; then
    echo "✅ Directory exists"
else
    echo "❌ Directory missing"
fi

echo ""
echo "6️⃣ SYSTEM STATUS SUMMARY"
echo "------------------------"
./safe-compose.sh ps

echo ""
echo "🎉 POST-REBOOT VERIFICATION COMPLETED"
echo "======================================"
echo "Completed at: $(date)"
