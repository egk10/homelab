Ceph integration notes for this docker-compose

Purpose
- Document how to switch Immich/Nextcloud/Vaultwarden to use your Ceph cluster (RGW S3 and CephFS/RBD mounts).
- Provide minimal commands to create RGW users/buckets and mount CephFS / map RBD on a host.

Assumptions
- You have an operational Ceph cluster with RGW enabled (radosgw) and CephFS/RBD available.
- The services are not yet in production and currently no important data is stored by the compose stack.
- You will run the RGW endpoint reachable from the Docker hosts (use Tailscale hostnames if necessary).

1) Create an RGW user and access keys

Run on a host with Ceph admin tools (or the RGW node):

```bash
# Create a user with radosgw-admin (generates JSON with keys)
sudo radosgw-admin user create --uid=immich --display-name="Immich user" > /tmp/immich-user.json

# Optional: create user with explicit keys
# sudo radosgw-admin user create --uid=immich --display-name="Immich user" --access-key=IMMICHKEY --secret=IMMICHSECRET

# Extract credentials (example using jq)
jq '.keys[0].access_key, .keys[0].secret_key' /tmp/immich-user.json
```

2) Create bucket (use aws-cli, s3cmd, or mc)

```bash
# Example using aws cli with RGW endpoint
AWS_ACCESS_KEY_ID=IMMICHKEY AWS_SECRET_ACCESS_KEY=IMMICHSECRET \
aws --endpoint-url=http://rgw-host:80 s3api create-bucket --bucket immich --region us-east-1
```

3) Set environment variables for docker-compose (example .env entries)

```
CEPH_S3_ACCESS_KEY_ID=IMMICHKEY
CEPH_S3_SECRET_ACCESS_KEY=IMMICHSECRET
CEPH_S3_ENDPOINT=http://rgw-host:80
CEPH_S3_BUCKET=immich
CEPH_S3_REGION=us-east-1
```

Reload or recreate the `immich-server` container with your new `.env` values.

4) Using CephFS or RBD for POSIX mounts (Nextcloud / Vaultwarden data)

Option A: Mount CephFS on each host (recommended for shared POSIX):

- Use kernel ceph mount or ceph-fuse. Kernel mount example:

```bash
sudo mkdir -p /mnt/ceph/nextcloud
sudo mount -t ceph mon1:6789:/ /mnt/ceph/nextcloud -o name=client.admin,secretfile=/etc/ceph/admin.secret,_netdev
```

- Add fstab with `_netdev` so the system waits for network before mounting.

Option B: Use RBD image for a single-writer mount (map per host or use for dedicated single-host services):

```bash
# Create RBD image on ceph admin
rbd create -p rbd pool/nextcloud --size 500G
# Map on host
sudo rbd map rbd/nextcloud --name client.admin
sudo mkfs.xfs /dev/rbd/rbd/nextcloud
sudo mkdir -p /mnt/nextcloud
sudo mount /dev/rbd/rbd/nextcloud /mnt/nextcloud
```

Then update your `docker-compose.yml` volumes to bind mount `/mnt/nextcloud:/var/www/html` for Nextcloud.

5) Backups with restic to Ceph RGW

- Initialize a restic repository on RGW:

```bash
export AWS_ACCESS_KEY_ID=BACKUPKEY
export AWS_SECRET_ACCESS_KEY=BACKUPSECRET
export RESTIC_REPOSITORY=s3:http://rgw-host:80/backup-bucket
restic init
```

- Create cron/systemd timers to run restic snapshots and to `pg_dump` Postgres DBs and push to the restic repo.

6) Notes on Tailnet and RGW reachability

- If your RGW endpoint is only reachable via Tailscale, set `CEPH_S3_ENDPOINT` to the Tailscale hostname or IP (for example `http://rgw-host.tailnet:80`). Ensure the docker host can resolve that name (MagicDNS or /etc/hosts).
- tsdproxy or Traefik on a tailnet-exposed host can also forward traffic to RGW if you want a stable friendly name.

7) Reverting the change

- The compose edit enabled S3 env vars for Immich and left the FUSE fallback volume intact; to revert, remove the `STORAGE_TYPE`/`S3_*` variables or restore your previous `docker-compose.yml` from git.


