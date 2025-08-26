#!/bin/bash

# Vaultwarden Backup Script
# Backs up Vaultwarden database to Ceph S3 storage
# Based on: https://github.com/dani-garcia/vaultwarden/wiki/Backing-up-your-vault

set -e

BACKUP_DIR="/tmp/vaultwarden_backup"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="vaultwarden_backup_${DATE}.tar.gz"
DB_BACKUP_FILE="db_${DATE}.sqlite3"

# Vaultwarden data location (S3FS mount)
VAULTWARDEN_DATA="/mnt/s3/vaultwarden"

# S3 Configuration
S3_ENDPOINT="http://100.90.57.27:80"
S3_ACCESS_KEY="uJ5CDvsCvVWTeCSBUUrQ"
S3_SECRET_KEY="Eg4qUsGsVu4gEXWsHpIv5xZ2Ao7Xe9AJefQMdLIw"
S3_BUCKET="vaultwarden-backups"

echo "🔄 Starting Vaultwarden backup at $(date)"

# Create backup directory
mkdir -p ${BACKUP_DIR}

# Method 1: SQLite backup using host sqlite3 (preferred)
echo "🗄️  Creating SQLite backup using host tools..."

# Check if sqlite3 is available on host
if command -v sqlite3 &> /dev/null; then
    # Use host sqlite3 to backup the database
    sqlite3 "${VAULTWARDEN_DATA}/db.sqlite3" ".backup ${BACKUP_DIR}/${DB_BACKUP_FILE}"
    echo "✅ SQLite backup created successfully using host tools"
else
    echo "⚠️  sqlite3 not available on host, using file copy method"
    # Fallback: Stop container and copy files
    echo "⏸️  Stopping Vaultwarden for file copy backup..."
    docker stop vaultwarden
    
    # Copy database file
    cp "${VAULTWARDEN_DATA}/db.sqlite3" "${BACKUP_DIR}/${DB_BACKUP_FILE}"
    
    # Restart Vaultwarden
    echo "▶️  Restarting Vaultwarden..."
    docker start vaultwarden
    
    # Wait for container to be ready
    sleep 5
    echo "✅ File copy backup completed"
fi

# Create complete backup archive including attachments, sends, etc.
echo "📦 Creating complete backup archive..."
cd ${VAULTWARDEN_DATA}
tar -czf ${BACKUP_DIR}/${BACKUP_FILE} \
    --exclude="db.sqlite3-wal" \
    --exclude="db.sqlite3-shm" \
    --exclude="tmp/*" \
    .

# If SQLite backup was successful, it's already in backup directory
# No need to move it

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

# Upload complete archive to S3
echo "☁️  Uploading complete backup to S3..."
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
    s3.upload_file('${BACKUP_DIR}/${BACKUP_FILE}', '${S3_BUCKET}', 'complete/${BACKUP_FILE}')
    print('✅ Complete backup uploaded successfully')
except Exception as e:
    print(f'❌ Upload failed: {e}')
"

# Upload SQLite backup separately (for quick restoration)
if [ -f "${BACKUP_DIR}/${DB_BACKUP_FILE}" ]; then
    echo "☁️  Uploading SQLite backup to S3..."
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
    s3.upload_file('${BACKUP_DIR}/${DB_BACKUP_FILE}', '${S3_BUCKET}', 'database/${DB_BACKUP_FILE}')
    print('✅ Database backup uploaded successfully')
except Exception as e:
    print(f'❌ Database upload failed: {e}')
"
fi

# Cleanup local backup
rm -rf ${BACKUP_DIR}

echo "✅ Vaultwarden backup completed at $(date)"
echo "📁 Complete backup: complete/${BACKUP_FILE}"
echo "📁 Database backup: database/${DB_BACKUP_FILE}"

# Keep only last 14 complete backups and 30 database backups
echo "🧹 Cleaning old backups..."
python3 -c "
import boto3
from botocore.client import Config
from datetime import datetime, timedelta

s3 = boto3.client('s3',
    endpoint_url='${S3_ENDPOINT}',
    aws_access_key_id='${S3_ACCESS_KEY}',
    aws_secret_access_key='${S3_SECRET_KEY}',
    region_name='us-east-1',
    config=Config(signature_version='s3v4')
)

def cleanup_backups(prefix, keep_count):
    try:
        response = s3.list_objects_v2(Bucket='${S3_BUCKET}', Prefix=prefix)
        if 'Contents' in response:
            backups = sorted(response['Contents'], key=lambda x: x['LastModified'], reverse=True)
            if len(backups) > keep_count:
                for backup in backups[keep_count:]:
                    s3.delete_object(Bucket='${S3_BUCKET}', Key=backup['Key'])
                    print(f'🗑️  Deleted old backup: {backup[\"Key\"]}')
            print(f'📊 {prefix} backups: {min(len(backups), keep_count)}')
    except Exception as e:
        print(f'❌ Cleanup error for {prefix}: {e}')

# Clean up complete backups (keep 14)
cleanup_backups('complete/', 14)

# Clean up database backups (keep 30)
cleanup_backups('database/', 30)
"

# Generate backup report
echo "📊 Generating backup report..."
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
        total_size = sum(obj['Size'] for obj in response['Contents'])
        complete_backups = [obj for obj in response['Contents'] if obj['Key'].startswith('complete/')]
        db_backups = [obj for obj in response['Contents'] if obj['Key'].startswith('database/')]
        
        print(f'📈 BACKUP SUMMARY:')
        print(f'   Complete backups: {len(complete_backups)}')
        print(f'   Database backups: {len(db_backups)}')
        print(f'   Total size: {total_size / 1024 / 1024:.1f} MB')
        print(f'   Latest complete: {max(complete_backups, key=lambda x: x[\"LastModified\"])[\"Key\"] if complete_backups else \"None\"}')
        print(f'   Latest database: {max(db_backups, key=lambda x: x[\"LastModified\"])[\"Key\"] if db_backups else \"None\"}')
except Exception as e:
    print(f'❌ Report error: {e}')
"
