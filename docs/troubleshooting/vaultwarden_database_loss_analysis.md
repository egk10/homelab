# Vaultwarden Database Loss Investigation & Resolution

## 📋 Issue Summary
**Problem**: Vaultwarden database becomes empty after system reboots, causing user login failures.
**Root Cause**: Race condition between Docker container startup and S3FS mount readiness.
**Resolution**: Implemented multi-layered preventive measures.

## 🔍 Root Cause Analysis

### The Problem Chain
1. **System Reboot** - Ubuntu server restarts
2. **Mount Delay** - S3FS services take time to establish connection to Ceph S3
3. **Docker Starts** - Docker service starts while mounts are not ready
4. **Container Race** - Vaultwarden container starts with `restart: always` policy
5. **Empty Directory** - Docker creates local empty `/mnt/s3/vaultwarden` directory
6. **New Database** - Vaultwarden creates new empty SQLite database
7. **Data Loss** - Original database in S3 is overshadowed by empty local database

### Timeline Evidence (Sep 22, 2025)
- **13:25:01** - System boot started
- **13:25:11** - S3FS Vaultwarden service mounted
- **13:27:18** - Docker service started (2+ minutes later)
- **Result** - Empty database with 0 users instead of expected 2 users

## 🛠️ Implemented Solutions

### 1. Docker Compose Health Check Service
**File**: `docker-compose.yml`
- Added `s3fs-healthcheck` container that validates mounts before Vaultwarden starts
- Vaultwarden now depends on successful completion of health check
- Health check verifies mount point is accessible and functional

### 2. Enhanced Container Health Checks
**File**: `docker-compose.yml` - Vaultwarden service
- Modified health check to verify mount point inside container
- Added longer start period (60s) to allow for mount stabilization
- Health check: `mountpoint -q /data && wget --spider http://127.0.0.1/alive`

### 3. Systemd Service Override
**File**: `/etc/systemd/system/docker.service.d/mount-safety.conf`
- Docker service now explicitly waits for all S3FS services
- Added 5-second startup delay for mount stabilization
- Pre-startup verification of mount points

### 4. Monitoring and Verification Tools
**Files**: 
- `scripts/maintenance/post_reboot_verification.sh` - Post-reboot health check
- `scripts/maintenance/s3fs_mount_healthcheck.sh` - Comprehensive mount validator
- `scripts/maintenance/check_s3fs_mount.sh` - Simple mount checker

### 5. Database Restoration Process
**Process**: Implemented backup restoration from restic snapshots
- Identified working backup from Sep 21 (snapshot 16b3ddda)
- Safely restored database with 2 users
- Created backup of corrupted empty database for analysis

## 🔧 Prevention Measures

### Startup Sequence (Fixed)
1. **Network Ready** - `network-online.target`
2. **S3FS Mounts** - All S3FS services establish connections
3. **Mount Health Check** - Docker health check container validates mounts
4. **Docker Containers** - Applications start only after mounts are verified

### Health Monitoring
- Post-reboot verification script detects empty databases immediately
- Regular backup system maintains recovery points
- Container health checks prevent service marked as healthy until mounts verified

## 🚨 Warning Signs for Future
- **Database size suddenly drops** (1.5MB → 250KB)
- **User count becomes 0** in post-reboot checks
- **Mount accessibility failures** in health checks
- **Container restart loops** around boot time

## 🔄 Recovery Process
If database loss occurs again:

1. **Stop Vaultwarden**: `docker compose stop vaultwarden`
2. **Verify Mount**: `mountpoint /mnt/s3/vaultwarden`
3. **List Backups**: `restic snapshots --tag vaultwarden --latest 5`
4. **Restore**: `restic restore SNAPSHOT_ID --target /tmp/restore`
5. **Replace Database**: Copy restored `db.sqlite3` to mount
6. **Start Service**: `docker compose start vaultwarden`
7. **Verify**: Check user count with verification script

## 📁 Key Files Modified
- `docker-compose.yml` - Added health check service and dependencies
- `/etc/systemd/system/docker.service.d/mount-safety.conf` - Systemd override
- `scripts/maintenance/post_reboot_verification.sh` - Monitoring script
- `scripts/maintenance/s3fs_mount_healthcheck.sh` - Health validator

## ✅ Verification
Run after any reboot:
```bash
/home/egk/homelab/scripts/maintenance/post_reboot_verification.sh
```

## 📊 Expected Healthy State
- **Vaultwarden DB size**: ~1.5MB
- **User count**: 2 (eliegkfouri@gmail.com, egkhain@gmail.com)
- **All mounts**: Accessible and mounted
- **Container health**: Healthy status after startup

---
**Investigation Date**: September 22, 2025  
**Resolved By**: GitHub Copilot Analysis  
**Status**: ✅ Resolved with comprehensive prevention measures