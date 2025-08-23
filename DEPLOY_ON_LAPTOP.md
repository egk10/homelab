# Deploy Docker Compose Stack on Laptop

This guide shows how to deploy the homelab stack on your laptop (`laptop.velociraptor-scylla.ts.net`) using your existing Ceph cluster.

## Your Tailscale Network
- **Laptop (deploy target)**: `laptop.velociraptor-scylla.ts.net` (100.122.225.91)
- **Ceph cluster nodes** (from screenshots): `eliedesk`, `minipcamd*`, `minitx`, etc.

## Pre-deployment steps (run on laptop)

### 1. Install required packages
```bash
# Install ceph-common for mounting CephFS/RBD
sudo apt update
sudo apt install ceph-common docker.io docker-compose-plugin

# Start docker service
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
# logout/login or newgrp docker
```

### 2. Set up Ceph client configuration
Copy Ceph configuration from one of your cluster nodes to the laptop:

```bash
# On a Ceph node (e.g., eliedesk), copy these files:
sudo scp /etc/ceph/ceph.conf laptop.velociraptor-scylla.ts.net:/tmp/
sudo scp /etc/ceph/ceph.client.admin.keyring laptop.velociraptor-scylla.ts.net:/tmp/

# On laptop, install the config:
sudo mkdir -p /etc/ceph
sudo mv /tmp/ceph.conf /etc/ceph/
sudo mv /tmp/ceph.client.admin.keyring /etc/ceph/
sudo chmod 600 /etc/ceph/ceph.client.admin.keyring
```

### 3. Create RGW user and bucket
Run this on any Ceph admin node (e.g., `eliedesk`):

```bash
# Use your script (copy homelab repo to Ceph admin node first)
./scripts/create_rgw_user_and_bucket.sh --uid immich --bucket immich
```

Save the output access key and secret key for your `.env` file.

### 4. Mount CephFS on laptop
```bash
# Create mount point
sudo mkdir -p /mnt/ceph

# Mount CephFS (replace mon IPs with your actual monitor nodes)
# Use Tailscale hostnames for monitors
sudo mount -t ceph eliedesk.velociraptor-scylla.ts.net:6789,minipcamd.velociraptor-scylla.ts.net:6789:/ /mnt/ceph -o name=client.admin,_netdev

# Create subdirectories for services
sudo mkdir -p /mnt/ceph/nextcloud /mnt/ceph/vaultwarden /mnt/ceph/immich
sudo chown -R $USER:$USER /mnt/ceph/
```

### 5. Make mount persistent (optional)
Add to `/etc/fstab`:
```
eliedesk.velociraptor-scylla.ts.net:6789,minipcamd.velociraptor-scylla.ts.net:6789:/  /mnt/ceph  ceph  name=client.admin,_netdev,noauto  0  0
```

## Deploy the stack

### 1. Clone and configure
```bash
# Clone your homelab repo on laptop
git clone <your-repo-url> homelab
cd homelab

# Copy and edit environment file
cp .env.example .env
```

### 2. Edit .env file
Set these values in `.env`:
```bash
# Database passwords
POSTGRES_PASSWORD=your_secure_postgres_password
REDIS_PASSWORD=your_secure_redis_password
MYSQL_PASSWORD=your_secure_mysql_password
MYSQL_ROOT_PASSWORD=your_secure_mysql_root_password

# Ceph RGW S3 (from step 3 above)
CEPH_S3_ACCESS_KEY_ID=<access_key_from_rgw_script>
CEPH_S3_SECRET_ACCESS_KEY=<secret_key_from_rgw_script>
CEPH_S3_ENDPOINT=http://eliedesk.velociraptor-scylla.ts.net:80  # or your RGW endpoint
CEPH_S3_BUCKET=immich
CEPH_S3_REGION=us-east-1

# Tailscale
TAILSCALE_AUTH_KEY=<your_tailscale_auth_key>

# Service domains (tsdproxy will handle these)
NEXTCLOUD_DOMAIN=nextcloud.velociraptor-scylla.ts.net
VAULTWARDEN_DOMAIN=https://vaultwarden.velociraptor-scylla.ts.net

# Vaultwarden admin token (generate with: echo -n "password" | argon2 "$(openssl rand -base64 32)" -e -id -k 65536 -t 3 -p 4)
ADMIN_TOKEN=<your_argon2_hash>

# Timezone
TZ=America/Toronto  # or your timezone
```

### 3. Start the stack
```bash
# Remove SeaweedFS services first (they're not needed with Ceph)
# You can comment them out in docker-compose.yml or:

# Start core services first
docker compose up -d immich-postgres immich-redis nextcloud-db

# Wait for DBs to be ready, then start apps
docker compose up -d immich-server nextcloud vaultwarden homeassistant

# Start proxy and monitoring
docker compose up -d tsdproxy watchtower
```

### 4. Access services
Once tsdproxy is running, your services will be available at:
- **Immich**: Via tsdproxy (check tsdproxy logs/UI for assigned URL)
- **Nextcloud**: Via tsdproxy 
- **Vaultwarden**: Via tsdproxy
- **Home Assistant**: `http://laptop.velociraptor-scylla.ts.net:8123`

## Troubleshooting

### Check Ceph connectivity
```bash
# Test Ceph cluster from laptop
ceph -s
ceph df
rados df
```

### Check mounts
```bash
df -h /mnt/ceph
ls -la /mnt/ceph/
```

### Check RGW S3 access
```bash
# Test with aws cli
AWS_ACCESS_KEY_ID=<key> AWS_SECRET_ACCESS_KEY=<secret> \
aws --endpoint-url=http://eliedesk.velociraptor-scylla.ts.net:80 s3 ls
```

### Container logs
```bash
docker compose logs immich-server
docker compose logs tsdproxy
```

## Next steps
- Set up restic backups using the `scripts/init_restic_repo.sh` script
- Configure monitoring with Prometheus/Grafana
- Set up automated updates and health checks
