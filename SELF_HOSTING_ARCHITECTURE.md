# Self-hosting architecture with Ceph for photos, documents and passwords

This document outlines a resilient, reliable self-host stack using your existing Ceph cluster and Tailscale private network. It includes recommended architecture, concrete configuration examples (Immich, Nextcloud, Vaultwarden), HA/deployment options, monitoring/backup plans, and next steps you can follow.

## Checklist (requirements extracted)
- Integrate your Ceph cluster to store photos, documents and other content. (S3 RGW + RBD/FS options)
- Provide resilient, reliable services replacing Google Photos, LastPass, Google Docs.
- Use the Tailscale private network between nodes (tailscale nodes.csv is available).
- Turn your draft `docker-compose.yml` into a production-grade deployment (recommend k3s or Docker Swarm).

## High-level plan
1. Choose orchestration: k3s (recommended) or Docker Swarm (easier migration from compose).
2. Use Ceph RGW (S3-compatible) for object storage where possible (Immich, backups, Restic). Use CephFS or RBD for services that require POSIX filesystem (Nextcloud primary storage, FUSE mounts).
3. Run services across multiple nodes, use persistent volumes (RBD mapped on each node or use CSI driver with k3s).
4. Add monitoring (Prometheus, Grafana, node-exporter, cAdvisor), alerting, and automated backups (restic -> Ceph RGW) and periodic DB dumps.
5. Use a reverse proxy with TLS (Traefik or Caddy). Optionally keep `tsdproxy` for Tailscale-only access.

## Orchestration options (short)
- k3s + Rook-Ceph: Best for resilience and native Ceph integration (CSI drivers, RBD, CephFS, RGW). Use Helm charts for apps. Recommended when you can run a lightweight K8s on your homelab nodes.
- Docker Swarm / Docker Stack: Simpler if you want to reuse your `docker-compose.yml`. You'll need to handle Ceph mounts yourself (kernel RBD or ceph-fuse on each node) or point apps to RGW S3.

Recommendation: If you're comfortable running Kubernetes, install k3s on the nodes and Rook to manage Ceph. This gives dynamic PVs, failover, and native Ceph use. If not, use Docker Swarm + S3 for object storage and RBD mounts for POSIX needs.

## Ceph integration patterns
1. S3 (RGW): Use when app supports S3 object storage (Immich, backups, restic). Configure endpoints like `http://rgw-host:80` (or HTTPS). Advantage: simple, multi-node safe.
2. RBD block devices / CephFS: Use when app needs real filesystem semantics (Nextcloud primary storage, FUSE mounts). Expose RBD volumes to each host using kernel rbd or ceph-fuse, or use CSI driver with k3s/Rook.
3. CephFS for shared POSIX filesystem used by many apps at once.

## Concrete examples

### Immich (photo service)
Prefer S3 (RGW) as object storage; configure in your `docker-compose` / deployment via environment variables.

Example env (Immich server):
- STORAGE_TYPE: s3
- S3_ACCESS_KEY_ID: <your_key>
- S3_SECRET_ACCESS_KEY: <your_secret>
- S3_ENDPOINT: http://<rgw-host>:8080    # or https
- S3_BUCKET: immich
- S3_FORCE_PATH_STYLE: "true"
- S3_REGION: us-east-1

Notes:
- Create the S3 bucket on RGW (or allow the service to create it). Ensure endpoint resolves from containers (use Tailscale DNS or host aliases).
- Keep `UPLOAD_LOCATION` as fallback to an RBD or CephFS mount if you like a FUSE fallback for local performance.

### Nextcloud (documents)
Two patterns:
- Primary storage on CephFS/RBD (recommended for reliability and performance): mount CephFS on each host at e.g. `/mnt/nextcloud` and map into container as `/var/www/html` persistent storage.
- Object storage via S3 for apps that support external object storage (some Nextcloud features require local FS): configure `config/objectstore.php` or use the `objectstore` app.

Example `config/objectstore.php` snippet for S3 (Nextcloud as external objectstore primary):
- see Nextcloud docs; you’ll need to provide S3-compatible settings and ensure compatibility for your version.

### Vaultwarden (passwords)
Vaultwarden is lightweight and stores data in SQLite by default. For resilience:
- Use a managed DB (Postgres) for WAL-style durability and to allow multi-node replicas.
- Keep `/data` stored on CephFS or an RBD-backed filesystem on the host.
- Ensure backups of DB and `/data` are taken with restic to S3 (RGW) or periodic filesystem snapshots.

### Backups (recommended setup)
- Use restic to push encrypted backups to Ceph RGW (S3 backend). Keep a separate backup user/credentials.
- DB backups: schedule `pg_dump` for Postgres (for Immich/Nextcloud/Vaultwarden if moved to Postgres) and push to restic.
- File backups: use restic to snapshot important paths, or rely on Ceph snapshots if using RBD/CephFS.

Sample restic repo URL: `s3:https://rgw-host:8080/backup-bucket`

### Monitoring & alerting
- Prometheus + node_exporter + cAdvisor to collect metrics.
- Grafana for dashboards.
- Alertmanager for alerts (email, webhook, or Signal/Telegram integration).

### Reverse proxy / TLS
Options:
- Traefik with ACME (lets you expose services publicly with automatic TLS). Works well in k3s/Swarm.
- Caddy (simple automatic TLS).
- Keep `tsdproxy` for Tailscale-only access if you want services to be reachable only inside the Tailscale network.

Recommendation: Use Traefik as the main proxy and configure rules for internal-only hosts. Use Tailscale + tailnet DNS for private resolution and keep Traefik’s ACME for public endpoints if desired.

## Upgrade and update strategy
- Use watchtower for automatic container updates (you already have it). For k3s/Swarm consider using Argo CD or Flux for GitOps.
- Test upgrades on a single node or staging namespace before rolling updates.

## Disaster recovery
- Keep at least 2 off-site encrypted backups (e.g., another home, external VPS, or Backblaze B2) via restic.
- Regularly test restores for DB and a small number of files.
- Keep Ceph cluster health checks and monitor OSD count and PG health.

## Example docker-compose adjustments (conceptual)
- Replace SeaweedFS services with configuration that uses Ceph RGW for S3 storage and CephFS/RBD mounts for POSIX file needs.
- For Immich, set STORAGE_TYPE to s3 and remove FUSE-only dependency if RGW is available.
- For Nextcloud, mount CephFS at `/mnt/nextcloud` and update volumes to point to that path.

I can transform your `docker-compose.yml` to:
- Remove seaweedfs containers and add example S3 config for Immich and objectstore config for Nextcloud.
- Add optional helper service `ceph-mount` or instructions to mount CephFS/RBD on each host.

Tell me if you want me to apply these exact changes to `docker-compose.yml` (I can create a safe branch update). If you prefer k3s + Helm charts, I can produce Helm manifests/Helmfile for Immich, Nextcloud, Vaultwarden, Traefik, Prometheus, and Rook-Ceph.

## Small checklist of next actions I can take for you now
- [ ] Edit `docker-compose.yml` to replace SeaweedFS with Ceph RGW S3 config + example mounts for CephFS/RBD.
- [ ] Produce k3s + Rook-Ceph Helm charts and example manifests for a full HA deployment.
- [ ] Add Prometheus/Grafana stack + alerting to the compose or k8s manifests.
- [ ] Add restic backup job examples and systemd timers or Kubernetes CronJobs.

Tell me which of the above you want me to implement first. If you want the `docker-compose.yml` updated now, I will create a branch and patch the file with the minimal, reversible changes.

---

## Requirements coverage
- Ceph integration: Explained patterns (Done – implementation examples included).
- Replace Google Photos/Docs/LastPass: Mapped to Immich/Nextcloud/Vaultwarden and how to configure them with Ceph (Done).
- Use Tailscale: Noted and recommended usage with tsdproxy and tailnet DNS (Done).
- Docker-compose draft -> production: Provided Orchestration options and next steps; I can edit `docker-compose.yml` on request (Partially done — decision needed).


