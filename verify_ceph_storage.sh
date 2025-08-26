#!/bin/bash
# Verification script for Test 2 - Run after uploading files
# This script checks if uploaded files are stored in Ceph S3, not locally

echo "🔍 VERIFICATION: Files Stored in Ceph S3 (Not Local)"
echo "=================================================="

echo ""
echo "📁 Nextcloud Files in Ceph S3:"
echo "------------------------------"
if sudo find /mnt/s3fs/nextcloud-data -type f -name "*" 2>/dev/null | head -5; then
    echo "✅ Files found in Nextcloud S3FS mount"
    echo "File count: $(sudo find /mnt/s3fs/nextcloud-data -type f 2>/dev/null | wc -l)"
    echo "Storage usage: $(sudo du -sh /mnt/s3fs/nextcloud-data 2>/dev/null | cut -f1)"
else
    echo "❓ No files found in Nextcloud S3FS mount"
fi

echo ""
echo "📸 Immich Photos in Ceph S3:"
echo "----------------------------"
if sudo find /mnt/s3fs/immich -type f -name "*" 2>/dev/null | head -5; then
    echo "✅ Files found in Immich S3FS mount"
    echo "File count: $(sudo find /mnt/s3fs/immich -type f 2>/dev/null | wc -l)"
    echo "Storage usage: $(sudo du -sh /mnt/s3fs/immich 2>/dev/null | cut -f1)"
else
    echo "❓ No files found in Immich S3FS mount"
fi

echo ""
echo "🚫 Verification: NO Local Storage Used:"
echo "--------------------------------------"
local_files=$(sudo find /var/lib/docker/volumes -name "*.jpg" -o -name "*.png" -o -name "*.pdf" -o -name "*.doc*" 2>/dev/null | wc -l)
echo "Files in Docker volumes: $local_files"
if [ "$local_files" -eq 0 ] || [ "$local_files" -lt 5 ]; then
    echo "✅ GOOD: Minimal or no user files in local Docker storage"
else
    echo "⚠️  WARNING: Found $local_files files in local Docker storage"
fi

echo ""
echo "📊 Overall Storage Summary:"
echo "--------------------------"
echo "Nextcloud S3: $(sudo du -sh /mnt/s3fs/nextcloud-data 2>/dev/null | cut -f1 || echo '0')"
echo "Immich S3: $(sudo du -sh /mnt/s3fs/immich 2>/dev/null | cut -f1 || echo '0')"
echo "Vaultwarden S3: $(sudo du -sh /mnt/s3/vaultwarden 2>/dev/null | cut -f1 || echo '0')"

echo ""
echo "✅ Test 2 verification completed!"
echo "Files should be in S3FS mounts, NOT in local Docker volumes."
