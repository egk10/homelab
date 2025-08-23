#!/usr/bin/env bash
# create_rgw_user_and_bucket.sh
# Interactive helper to create an RGW user and a bucket, and print credentials for use in .env
# Run on a host with radosgw-admin and aws CLI available and configured (or provide endpoint via env)

set -euo pipefail

usage() {
  cat <<EOF
Usage: $0 [--uid UID] [--display-name NAME] [--bucket BUCKET] [--access-key KEY] [--secret SECRET] [--endpoint ENDPOINT]

This script will:
 - create an RGW user with radosgw-admin (or show how to create with explicit keys)
 - output the access_key and secret_key
 - (optionally) create an S3 bucket using aws CLI pointing at the RGW endpoint

You must run this on a Ceph admin host (or a host with radosgw-admin and proper admin keyring).
EOF
  exit 1
}

# Defaults
UID="immich"
DISPLAY_NAME="Immich user"
BUCKET="immich"
ACCESS_KEY=""
SECRET_KEY=""
ENDPOINT="${CEPH_S3_ENDPOINT:-http://rgw-host:80}"
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --uid) UID="$2"; shift 2;;
    --display-name) DISPLAY_NAME="$2"; shift 2;;
    --bucket) BUCKET="$2"; shift 2;;
    --access-key) ACCESS_KEY="$2"; shift 2;;
    --secret) SECRET_KEY="$2"; shift 2;;
    --endpoint) ENDPOINT="$2"; shift 2;;
    --dry-run) DRY_RUN=true; shift 1;;
    -h|--help) usage;;
    *) echo "Unknown arg: $1"; usage;;
  esac
done

command -v radosgw-admin >/dev/null 2>&1 || { echo "radosgw-admin not found in PATH; install ceph tools and try again."; exit 2; }
command -v aws >/dev/null 2>&1 || echo "aws CLI not found; bucket creation step will be skipped."
command -v jq >/dev/null 2>&1 || echo "jq not found; output parsing will be raw JSON."

echo "Creating RGW user: uid=$UID display-name='$DISPLAY_NAME'"
if [ -n "$ACCESS_KEY" ] && [ -n "$SECRET_KEY" ]; then
  echo "Using provided access/secret keys"
  if [ "$DRY_RUN" = true ]; then
    echo "DRY RUN - would run: radosgw-admin user create --uid=$UID --display-name=\"$DISPLAY_NAME\" --access-key=$ACCESS_KEY --secret=$SECRET_KEY"
  else
    sudo radosgw-admin user create --uid="$UID" --display-name="$DISPLAY_NAME" --access-key="$ACCESS_KEY" --secret="$SECRET_KEY" > "/tmp/${UID}-user.json"
  fi
else
  if [ "$DRY_RUN" = true ]; then
    echo "DRY RUN - would run: radosgw-admin user create --uid=$UID --display-name=\"$DISPLAY_NAME\""
  else
    sudo radosgw-admin user create --uid="$UID" --display-name="$DISPLAY_NAME" > "/tmp/${UID}-user.json"
  fi
fi

if [ -f "/tmp/${UID}-user.json" ]; then
  echo "User JSON written to /tmp/${UID}-user.json"
  if command -v jq >/dev/null 2>&1; then
    ACCESS_KEY_OUT=$(jq -r '.keys[0].access_key' /tmp/${UID}-user.json)
    SECRET_KEY_OUT=$(jq -r '.keys[0].secret_key' /tmp/${UID}-user.json)
    echo "Access Key: $ACCESS_KEY_OUT"
    echo "Secret Key: $SECRET_KEY_OUT"
  else
    echo "Contents of /tmp/${UID}-user.json:"; sed -n '1,200p' /tmp/${UID}-user.json
  fi
else
  echo "No user JSON found (dry-run or failure)."
fi

# Create bucket if aws CLI is available
if command -v aws >/dev/null 2>&1; then
  if [ "$DRY_RUN" = true ]; then
    echo "DRY RUN - would run: AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... aws --endpoint-url=$ENDPOINT s3api create-bucket --bucket $BUCKET --region us-east-1"
  else
    echo "Creating bucket '$BUCKET' on endpoint $ENDPOINT"
    echo "Please set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in the environment to the user's keys above, or press Enter to skip bucket creation..."
    read -r -p "Create bucket now? [y/N]: " create_bucket
    if [[ "$create_bucket" =~ ^[Yy]$ ]]; then
      read -rp "AWS_ACCESS_KEY_ID: " env_ak
      read -rp "AWS_SECRET_ACCESS_KEY: " env_sk
      AWS_ACCESS_KEY_ID="$env_ak" AWS_SECRET_ACCESS_KEY="$env_sk" aws --endpoint-url="$ENDPOINT" s3api create-bucket --bucket "$BUCKET" --region us-east-1 || {
        echo "Bucket creation failed. You can create it manually with the aws CLI or s3cmd/mc.";
      }
    else
      echo "Skipping bucket creation."
    fi
  fi
else
  echo "aws CLI not present; skipping bucket creation. You can use mc/s3cmd or the RGW admin web UI."
fi

echo "Done. Add the keys to your .env file as CEPH_S3_ACCESS_KEY_ID and CEPH_S3_SECRET_ACCESS_KEY."

exit 0
