#!/bin/bash

# Home Assistant Backup Script
# Backs up Home Assistant configuration to Ceph S3 storage

set -e

BACKUP_DIR="/tmp/homeassistant_backup"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="homeassistant_backup_${DATE}.tar.gz"

# Home Assistant data location (local volume)
HA_DATA_VOLUME="homelab_homeassistant_config"
HA_CONTAINER="homeassistant"

# S3 Configuration
S3_ENDPOINT="http://your-ceph-rgw-ip:80"
S3_ACCESS_KEY="uJ5CDvsCvVWTeCSBUUrQ"
S3_SECRET_KEY="Eg4qUsGsVu4gEXWsHpIv5xZ2Ao7Xe9AJefQMdLIw"
S3_BUCKET="homeassistant-backups"

echo "🔄 Starting Home Assistant backup at $(date)"

# Create backup directory
mkdir -p ${BACKUP_DIR}

# Stop Home Assistant for consistent backup
echo "⏸️  Stopping Home Assistant..."
docker stop ${HA_CONTAINER}

# Create backup using docker volume
echo "📦 Creating backup from Docker volume..."
docker run --rm \
    -v ${HA_DATA_VOLUME}:/source:ro \
    -v ${BACKUP_DIR}:/backup \
    alpine:latest \
    tar -czf /backup/${BACKUP_FILE} -C /source .

# Restart Home Assistant
echo "▶️  Restarting Home Assistant..."
docker start ${HA_CONTAINER}

# Wait for container to be ready
sleep 10

# Create S3 bucket if it doesn't exist
echo "🪣 Ensuring S3 bucket exists..."
python3 -c "
import boto3
from botocore.client import Config

s3 = boto3.client('s3',
    endpoint_url='${S3_ENDPOINT}',
    aws_access_key_id='${S3_ACCESS_KEY}',
    aws_secret_access_key='${S3_SECRET_KEY}',
    region_name='us-east-1',
    config=Config(signature_version='s3v4')
)

try:
    s3.create_bucket(Bucket='${S3_BUCKET}')
    print('✅ Created backup bucket')
except Exception as e:
    if 'BucketAlreadyOwnedByYou' in str(e):
        print('✅ Backup bucket already exists')
    else:
        print(f'❌ Error: {e}')
"

# Upload to S3
echo "☁️  Uploading backup to S3..."
python3 -c "
import boto3
from botocore.client import Config

s3 = boto3.client('s3',
    endpoint_url='${S3_ENDPOINT}',
    aws_access_key_id='${S3_ACCESS_KEY}',
    aws_secret_access_key='${S3_SECRET_KEY}',
    region_name='us-east-1',
    config=Config(signature_version='s3v4')
)

try:
    s3.upload_file('${BACKUP_DIR}/${BACKUP_FILE}', '${S3_BUCKET}', '${BACKUP_FILE}')
    print('✅ Backup uploaded successfully')
except Exception as e:
    print(f'❌ Upload failed: {e}')
"

# Cleanup local backup
rm -rf ${BACKUP_DIR}

echo "✅ Home Assistant backup completed at $(date)"
echo "📁 Backup stored as: ${BACKUP_FILE}"

# Keep only last 30 backups
echo "🧹 Cleaning old backups (keeping last 30)..."
python3 -c "
import boto3
from botocore.client import Config

s3 = boto3.client('s3',
    endpoint_url='${S3_ENDPOINT}',
    aws_access_key_id='${S3_ACCESS_KEY}',
    aws_secret_access_key='${S3_SECRET_KEY}',
    region_name='us-east-1',
    config=Config(signature_version='s3v4')
)

try:
    response = s3.list_objects_v2(Bucket='${S3_BUCKET}')
    if 'Contents' in response:
        backups = sorted(response['Contents'], key=lambda x: x['LastModified'], reverse=True)
        if len(backups) > 30:
            for backup in backups[30:]:
                s3.delete_object(Bucket='${S3_BUCKET}', Key=backup['Key'])
                print(f'🗑️  Deleted old backup: {backup[\"Key\"]}')
        print(f'📊 Total backups: {min(len(backups), 30)}')
        total_size = sum(obj['Size'] for obj in backups[:30])
        print(f'📈 Total backup size: {total_size / 1024 / 1024:.1f} MB')
except Exception as e:
    print(f'❌ Cleanup error: {e}')
"
