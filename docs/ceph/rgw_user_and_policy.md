RGW user and least-privilege policy (instructions)

This document explains how to create a per-application RGW user and a bucket, and a minimal policy that limits the user's access to that bucket.

Prerequisites: run these on a Ceph admin host with `radosgw-admin` installed and working.

1) Create the user (example):

radosgw-admin user create --uid="immich_user" --display-name="Immich user" > /tmp/immich-user.json

Extract keys:
jq -r '.keys[0].access_key' /tmp/immich-user.json
jq -r '.keys[0].secret_key' /tmp/immich-user.json

2) Create the bucket (using s3cmd/mc/aws):
# using aws cli with endpoint
AWS_ACCESS_KEY_ID=IMMICH_KEY AWS_SECRET_ACCESS_KEY=IMMICH_SECRET aws --endpoint-url=https://rgw.example.com s3api create-bucket --bucket immich --region us-east-1

3) Policy (example)

# Create an IAM style policy that only permits list/get/put on the immich bucket
cat > /tmp/immich-policy.json <<'EOF'
{
  "Version":"2012-10-17",
  "Statement":[
    {
      "Effect":"Allow",
      "Action":[
        "s3:ListBucket",
        "s3:GetBucketLocation"
      ],
      "Resource":"arn:aws:s3:::immich"
    },
    {
      "Effect":"Allow",
      "Action":[
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:ListMultipartUploadParts",
        "s3:AbortMultipartUpload"
      ],
      "Resource":"arn:aws:s3:::immich/*"
    }
  ]
}
EOF

# Apply the policy using radosgw-admin
radosgw-admin policy put --uid=immich_user --policy-name=immich_policy --policy-file=/tmp/immich-policy.json

4) Notes
- Use HTTPS endpoint in production.
- Rotate keys periodically and update `.env` or the docker secret.
- Test access from the app host (aws CLI or s3 client).

