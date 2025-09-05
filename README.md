# 🏠 Production Homelab - Ceph + Tailscale Integration

**Status:** 🚀 **PRODUCTION READY** ✅  
**Tested:** August 26, 2025 - All 3-tier tests passed  

## 🎯 Overview

Self-hosted services running on a homelab server, accessible from anywhere via Tailscale VPN, with data redundancy and reliability provided by a Ceph storage cluster.

### ✅ Services
- **🗃️ Nextcloud** - File storage and collaboration  
- **📸 Immich** - Photo and video management
- **🔐 Vaultwarden** - Password manager
- **🏡 Home Assistant** - Smart home automation

### ✅ Architecture Highlights
- **Clean S3 Data-Only Design** - User data exclusively in Ceph S3
- **Auto-Recovery System** - S3FS auto-mounts after reboot
- **Production Stability** - Comprehensive testing validation
- **Zero Downtime** - Bulletproof container management

## 🚀 Quick Start

### Prerequisites
- Ceph cluster with S3 gateway configured
- Tailscale account and auth key
- Ubuntu Server 24.04+

### Deployment
```bash
# 1. Clone repository
git clone https://github.com/egk10/homelab.git
cd homelab

# 2. Configure environment - Copy all example files
cp .env.example .env
cp config/docker/docker-compose.example.yml config/docker/docker-compose.yml
cp "config/tailscale/nodes.csv.example" "tailscale nodes.csv"
cp tsdproxy/config/authkey.example tsdproxy/config/authkey
cp tsdproxy/config/tsdproxy.yaml.example tsdproxy/config/tsdproxy.yaml
cp scripts/backup/backup_vaultwarden.sh.example scripts/backup/backup_vaultwarden.sh
cp scripts/setup/mount-s3fs.sh.example scripts/setup/mount-s3fs.sh
cp services/systemd/s3fs-*.service.example services/systemd/s3fs-nextcloud-data.service
cp services/systemd/s3fs-immich.service.example services/systemd/s3fs-immich.service  
cp services/systemd/s3fs-vaultwarden.service.example services/systemd/s3fs-vaultwarden.service
# Edit all files with your actual credentials and configuration

# 3. Install S3FS services
sudo cp services/systemd/s3fs-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable s3fs-nextcloud-data.service s3fs-immich.service s3fs-vaultwarden.service

# 4. Start services safely
./safe-compose.sh up -d
```

### Access Your Services
- **Nextcloud**: https://nextcloud.your-tailscale-domain.ts.net
- **Immich**: https://immich.your-tailscale-domain.ts.net  
- **Vaultwarden**: https://vaultwarden.your-tailscale-domain.ts.net
- **Home Assistant**: https://homeassistant.your-tailscale-domain.ts.net

## � Mobile Access Recommendation

**Recommended Mobile App:** [Keyguard](https://github.com/AChep/keyguard-app)  
Keyguard is an open-source Bitwarden-compatible client that works reliably with self-hosted Vaultwarden instances. It provides full sync functionality without the restrictions imposed by the official Bitwarden mobile app on self-hosted servers.

### Keyguard Setup:
1. Download from [F-Droid](https://f-droid.org/packages/com.artemchep.keyguard/) or [GitHub Releases](https://github.com/AChep/keyguard-app/releases)
2. Add your Vaultwarden server URL
3. Login with your credentials
4. Enjoy seamless password synchronization

**Official Setup Instructions:** [Keyguard GitHub](https://github.com/AChep/keyguard-app?tab=readme-ov-file#keyguard)

## 🔄 Backup & Recovery

### Automated Backup System

This homelab includes a comprehensive automated backup system for all services:

#### Vaultwarden Backup
- **Frequency:** Daily via systemd timer
- **Storage:** Ceph S3 bucket (`vaultwarden-backups`)
- **Method:** SQLite database dumps with WAL mode
- **Retention:** Last 30 backups maintained
- **Verification:** Automatic integrity checks

**Backup Script:** `scripts/backup/backup_vaultwarden.sh`
```bash
# Manual backup execution
./scripts/backup/backup_vaultwarden.sh

# Check backup status
ls -la /mnt/s3/vaultwarden/db_*.sqlite3
```

#### Other Services Backup
- **Nextcloud:** User data stored in Ceph S3 (`nextcloud-data` bucket)
- **Immich:** Photos/videos stored in Ceph S3 (`immich-uploads` bucket)
- **Home Assistant:** Configuration backed up via automated scripts

### Backup Verification
```bash
# Test backup restoration (simulation)
./scripts/backup_vaultwarden.sh

# Verify backup integrity
sqlite3 /mnt/s3/vaultwarden/db_20250101_120000.sqlite3 "PRAGMA integrity_check;"
```

### Emergency Recovery
```bash
# Stop Vaultwarden
docker compose stop vaultwarden

# Restore from backup
cp /mnt/s3/vaultwarden/db_20250101_120000.sqlite3 /mnt/s3/vaultwarden/db.sqlite3

# Start Vaultwarden
docker compose start vaultwarden
```

### Backup Monitoring
- **Logs:** `/home/egk/homelab/logs/backup_*.log`
- **Status:** Check systemd timer status
- **Storage:** Monitor Ceph S3 bucket usage

```
homelab/
├── 📋 README.md                          # Main documentation
├── ⚙️ .env.example                       # Environment template
├── 🛡️ .gitignore                        # Git ignore rules
├── 🐳 config/docker/                     # Docker configurations
│   ├── docker-compose.yml               # Service definitions
│   └── docker-compose.example.yml       # Template for new deployments
├── 🔧 config/                            # Configuration files
│   ├── ceph/                            # Ceph storage configs
│   ├── tailscale/                       # Tailscale network configs
│   └── nextcloud/                       # Nextcloud specific configs
├── �️ services/                          # Service configurations
│   ├── systemd/                         # Systemd service files
│   └── homeassistant/                   # Home Assistant configs
├── 📜 scripts/                           # Operational scripts
│   ├── backup/                          # Backup automation
│   ├── setup/                           # Initial setup scripts
│   ├── maintenance/                     # Maintenance utilities
│   └── monitoring/                      # Health monitoring
├── 📚 docs/                              # Documentation
│   ├── guides/                          # User guides
│   ├── troubleshooting/                 # Troubleshooting docs
│   └── ceph/                            # Ceph-specific docs
├── 🔨 tools/                             # Utility tools
├── 🌐 tsdproxy/                          # Tailscale proxy config
├── 📝 logs/                              # Application logs
└── 💾 backups/                           # Backup storage
```

## 🛡️ Production Features

### Auto-Recovery
- **S3FS Auto-Mount**: All storage services start automatically after reboot
- **Safe Container Startup**: Pre-flight verification prevents issues
- **Health Monitoring**: Continuous service validation

### Data Protection  
- **Ceph S3 Storage**: All user data stored in redundant Ceph cluster
- **Automated Backups**: Daily backups of critical services
- **Zero Local Storage**: No risk of data loss during failures

### Security
- **Tailscale VPN**: Encrypted access from anywhere
- **No Port Forwarding**: All external access through secure VPN
- **Service Isolation**: Container-based architecture

## � Security & Configuration

### Required Configuration Files
This repository uses example files to protect sensitive information:

```bash
# Copy and customize these files with your actual values:
cp .env.example .env                           # Database passwords, tokens
cp docker-compose.example.yml docker-compose.yml  # Service configuration  
cp "tailscale nodes.csv.example" "tailscale nodes.csv"  # Device information
cp tsdproxy/config/authkey.example tsdproxy/config/authkey  # Tailscale auth (ONLY location needed)
cp tsdproxy/config/tsdproxy.yaml.example tsdproxy/config/tsdproxy.yaml  # Proxy config
cp scripts/backup_vaultwarden.sh.example scripts/backup_vaultwarden.sh  # Backup script
cp scripts/mount-s3fs.sh.example scripts/mount-s3fs.sh  # S3FS mount script
cp s3fs-nextcloud-data.service.example s3fs-nextcloud-data.service  # Systemd services
cp s3fs-immich.service.example s3fs-immich.service
cp s3fs-vaultwarden.service.example s3fs-vaultwarden.service
```

### Security Features
- **Tailscale VPN**: Encrypted access from anywhere
- **No Port Forwarding**: All external access through secure VPN
- **Service Isolation**: Container-based architecture
- **Credential Protection**: Sensitive files in .gitignore

## �🔄 Operations

### Daily Management
```bash
# Check system status
./tools/safe-compose.sh ps

# View service logs  
docker-compose logs -f nextcloud

# Verify storage health
./tools/verify_ceph_storage.sh

# Test remote access
./tools/test_tailscale_domains.sh
```

### After Reboot
```bash
# System auto-recovers, but verify with:
./test3_post_reboot.sh
```

## 📊 Testing Validation

This homelab has passed comprehensive production testing:

- ✅ **Test 1**: Container restart + Tailscale domain access
- ✅ **Test 2**: File upload verification to Ceph S3  
- ✅ **Test 3**: Server reboot + complete auto-recovery

## 📖 Documentation

- **[PRODUCTION_READY.md](PRODUCTION_READY.md)** - Complete production guide
- **[ceph_integration_README.md](ceph_integration_README.md)** - Ceph setup details
- **[SELF_HOSTING_ARCHITECTURE.md](SELF_HOSTING_ARCHITECTURE.md)** - Architecture overview

## 🆘 Support

### Common Issues
1. **Services not starting**: Run `./scripts/verify_s3fs_mounts.sh`
2. **Storage not accessible**: Check `./verify_ceph_storage.sh`
3. **Remote access failing**: Verify `./test_tailscale_domains.sh`

### Emergency Recovery
```bash
# Restart S3FS services
sudo systemctl restart s3fs-*.service

# Restart containers safely
./safe-compose.sh down && ./safe-compose.sh up -d
```

---

**🎉 Production-Ready Homelab**  
*Self-hosted • Secure • Reliable • Tested*
