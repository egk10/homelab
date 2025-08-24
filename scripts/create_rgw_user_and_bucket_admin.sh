#!/usr/bin/env bash
# create_rgw_user_and_bucket_admin.sh
# Run this on a Ceph admin host (where /etc/ceph and radosgw-admin are present).
# Creates a least-privilege RGW user for Immich, creates a bucket, applies a restrictive bucket policy,
# and emits a ready-to-paste `.env` snippet (written to ./immich_rgw.env).
#
# Usage:
#   sudo ./create_rgw_user_and_bucket_admin.sh --bucket immich-uploads --uid immich --endpoint http://100.64.163.40:80
#
set -euo pipefail

usage() {
  cat <<EOF
Usage: $0 [--uid UID] [--bucket BUCKET] [--access-key ACCESS] [--secret SECRET] [--endpoint RGW_ENDPOINT]

Runs as root (or with sudo) on a Ceph admin host. It will:
  - create a new RGW user with supplied or generated keys
  - show the radosgw-admin user info
  - (optional) create the bucket via aws-cli (if aws present and --endpoint given)
  - emit ./immich_rgw.env with the minimal env vars for Immich

Examples:
  sudo $0 --uid immich --bucket immich-uploads --endpoint http://100.64.163.40:80
EOF
  exit 2
}

# defaults
IMMICH_UID=immich
IMMICH_BUCKET=immich-uploads
RGW_ENDPOINT=""
IMMICH_ACCESS_KEY=""
IMMICH_SECRET_KEY=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --uid) IMMICH_UID="$2"; shift 2;;
    --bucket) IMMICH_BUCKET="$2"; shift 2;;
    --access-key) IMMICH_ACCESS_KEY="$2"; shift 2;;
    --secret) IMMICH_SECRET_KEY="$2"; shift 2;;
    --endpoint) RGW_ENDPOINT="$2"; shift 2;;
    -h|--help) usage;;
    *) echo "Unknown arg: $1"; usage;;
  esac
done

# require radosgw-admin available
if ! command -v radosgw-admin >/dev/null 2>&1; then
  echo "radosgw-admin not found in PATH. Run this on the Ceph admin node where ceph is installed." >&2
  exit 3
fi

# warn about keyring
if [ ! -f /etc/ceph/ceph.client.admin.keyring ] && [ ! -f /etc/ceph/keyring ]; then
  echo "Warning: could not find an admin keyring under /etc/ceph. radosgw-admin may fail unless run where ceph admin files are present." >&2
fi

# generate keys if not supplied
if [ -z "$IMMICH_ACCESS_KEY" ]; then
  IMMICH_ACCESS_KEY=$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 20)
fi
if [ -z "$IMMICH_SECRET_KEY" ]; then
  IMMICH_SECRET_KEY=$(head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 40)
fi

echo "Creating RGW user: uid='$IMMICH_UID' bucket='$IMMICH_BUCKET'"

# create user
set -x
sudo radosgw-admin user create \
  --uid="$IMMICH_UID" \
  --display-name="Immich application user" \
  --email="ops@example.local" \
  --access-key="$IMMICH_ACCESS_KEY" \
  --secret="$IMMICH_SECRET_KEY"
set +x

# show the created user info
echo "\nUser info (JSON):"
sudo radosgw-admin user info --uid="$IMMICH_UID" | jq .

CANONICAL_ID=$(sudo radosgw-admin user info --uid="$IMMICH_UID" | jq -r '.user_id // .s3['"'canonical_id'"'] // empty')
if [ -z "$CANONICAL_ID" ]; then
  # try alternative fields
  CANONICAL_ID=$(sudo radosgw-admin user info --uid="$IMMICH_UID" | jq -r '.s3.canonical_id // .swift // empty')
fi

echo "\nCanonical ID: $CANONICAL_ID"

# emit policy.json using canonical id (if found)
POLICY_FILE="./immich_bucket_policy.json"
cat > "$POLICY_FILE" <<POL
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowOwnUserFullAccess",
      "Effect": "Allow",
      "Principal": { "CanonicalUser": "${CANONICAL_ID}" },
      "Action": "s3:*",
      "Resource": [
        "arn:aws:s3:::${IMMICH_BUCKET}",
        "arn:aws:s3:::${IMMICH_BUCKET}/*"
      ]
    }
  ]
}
POL

echo "Wrote bucket policy template to $POLICY_FILE"

# if aws-cli and endpoint provided, attempt to create bucket and apply policy
if command -v aws >/dev/null 2>&1 && [ -n "$RGW_ENDPOINT" ]; then
  echo "Detected aws-cli and endpoint provided; attempting to create bucket and apply policy using the new credentials."
  export AWS_ACCESS_KEY_ID="$IMMICH_ACCESS_KEY"
  export AWS_SECRET_ACCESS_KEY="$IMMICH_SECRET_KEY"

  aws --endpoint-url="$RGW_ENDPOINT" s3api create-bucket --bucket "$IMMICH_BUCKET" || true
  # put private ACL
  aws --endpoint-url="$RGW_ENDPOINT" s3api put-bucket-acl --bucket "$IMMICH_BUCKET" --acl private || true
  # attempt to apply policy
  aws --endpoint-url="$RGW_ENDPOINT" s3api put-bucket-policy --bucket "$IMMICH_BUCKET" --policy file://$POLICY_FILE || true

  # test upload
  echo "upload-test" > /tmp/rgw-immich-test.txt
  aws --endpoint-url="$RGW_ENDPOINT" s3 cp /tmp/rgw-immich-test.txt s3://$IMMICH_BUCKET/test.txt || true
  echo "List objects:" 
  aws --endpoint-url="$RGW_ENDPOINT" s3 ls s3://$IMMICH_BUCKET || true
  rm -f /tmp/rgw-immich-test.txt
else
  echo "aws-cli not present or RGW endpoint not supplied; skipping bucket creation and policy application."
  echo "If you want the script to create the bucket and apply policy, rerun with --endpoint <RGW_ENDPOINT> and ensure aws-cli is installed."
fi

# write .env snippet (file not committed)
ENV_OUT=./immich_rgw.env
cat > "$ENV_OUT" <<ENV
# immich RGW per-app credentials (DO NOT COMMIT)
CEPH_S3_ENDPOINT=${RGW_ENDPOINT:-http://100.64.163.40:80}
CEPH_S3_ACCESS_KEY_ID=${IMMICH_ACCESS_KEY}
CEPH_S3_SECRET_ACCESS_KEY=${IMMICH_SECRET_KEY}
CEPH_S3_BUCKET=${IMMICH_BUCKET}
ENV

chmod 600 "$ENV_OUT" || true

echo "\nWrote credentials snippet to $ENV_OUT (chmod 600). Paste values into your homelab .env or better: create Docker secrets using scripts/load_docker_secrets.sh"

echo "Script complete. If you want, run the following to revoke the user later if needed:\n  sudo radosgw-admin user rm --uid=\"$IMMICH_UID\" --purge-data"

exit 0
