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
cp docker-compose.example.yml docker-compose.yml
cp "tailscale nodes.csv.example" "tailscale nodes.csv"
cp tsdproxy/config/authkey.example tsdproxy/config/authkey
cp tsdproxy/config/tsdproxy.yaml.example tsdproxy/config/tsdproxy.yaml
cp scripts/backup_vaultwarden.sh.example scripts/backup_vaultwarden.sh
cp scripts/mount-s3fs.sh.example scripts/mount-s3fs.sh
cp s3fs-*.service.example s3fs-nextcloud-data.service
cp s3fs-immich.service.example s3fs-immich.service  
cp s3fs-vaultwarden.service.example s3fs-vaultwarden.service
# Edit all files with your actual credentials and configuration

# 3. Install S3FS services
sudo cp s3fs-*.service /etc/systemd/system/
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

## 📁 Repository Structure

```
homelab/
├── 📋 PRODUCTION_READY.md          # Complete production documentation
├── 🐳 docker-compose.example.yml   # Service template (copy to docker-compose.yml)
├── ⚙️ .env.example                 # Environment template (copy to .env)
├── 🛡️ safe-compose.sh              # Safe container management
├── 🔧 s3fs-*.service.example       # S3FS systemd service templates
├── 🧪 test3_post_reboot.sh         # Post-reboot verification
├── ✅ verify_ceph_storage.sh       # Storage validation
├── 🌐 test_tailscale_domains.sh    # Domain access testing
├── 🔧 tsdproxy/
│   └── config/
│       ├── authkey.example         # Tailscale auth template
│       └── tsdproxy.yaml.example   # Proxy config template
└── 📜 scripts/                     # Operational scripts
    ├── backup_vaultwarden.sh.example  # Backup script template
    ├── backup_homeassistant.sh
    ├── mount-s3fs.sh.example       # S3FS mount template
    ├── verify_s3fs_mounts.sh       # Mount verification
    └── create_rgw_user_and_bucket.sh
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
./safe-compose.sh ps

# View service logs  
docker-compose logs -f nextcloud

# Verify storage health
./verify_ceph_storage.sh

# Test remote access
./test_tailscale_domains.sh
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
