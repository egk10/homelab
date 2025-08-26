# Tailscale Authentication Setup

## Simplified Single-Location Auth Key Configuration

**IMPORTANT**: We've simplified the Tailscale configuration to use **ONLY ONE LOCATION** for the auth key.

### Configuration Location
- **ONLY LOCATION**: `tsdproxy/config/authkey` file
- **NOT USED**: `.env` file (removed TAILSCALE_AUTH_KEY)  
- **NOT USED**: Inline `authKey` in `tsdproxy.yaml` (only uses `authKeyFile`)

### Setup Steps

1. **Get Tailscale Auth Key**
   - Go to: https://login.tailscale.com/admin/settings/keys
   - Create new auth key with these settings:
     - **Reusable**: YES (very important)
     - **Ephemeral**: YES (nodes removed when tsdproxy stops)
     - **Expiry**: 90 days or longer

2. **Configure Auth Key (ONLY location needed)**
   ```bash
   # Copy the example file
   cp tsdproxy/config/authkey.example tsdproxy/config/authkey
   
   # Edit the file and replace the placeholder with your real key
   nano tsdproxy/config/authkey
   
   # Secure the file
   chmod 600 tsdproxy/config/authkey
   ```

3. **Verify Configuration**
   ```bash
   # The tsdproxy.yaml should reference the file (not inline key)
   grep authKeyFile tsdproxy/config/tsdproxy.yaml
   # Should show: authKeyFile: "/config/authkey"
   ```

### Benefits of Single-Location Approach

- ✅ **Security**: Key stored in one secure file with proper permissions
- ✅ **Simplicity**: No need to update multiple locations
- ✅ **Maintenance**: Easy key rotation (update one file)
- ✅ **Git Safety**: Only one file to keep in .gitignore

### Key Rotation Process

```bash
# 1. Generate new key in Tailscale admin
# 2. Update single file
echo "tskey-auth-NEW_KEY_HERE" > tsdproxy/config/authkey
chmod 600 tsdproxy/config/authkey

# 3. Restart tsdproxy
docker compose up -d --no-deps --force-recreate tsdproxy
```

### Troubleshooting

If tsdproxy fails to authenticate:
1. Verify key is reusable and not expired
2. Check file permissions: `ls -la tsdproxy/config/authkey`
3. Verify file content: `cat tsdproxy/config/authkey`
4. Check tsdproxy logs: `docker compose logs tsdproxy`
