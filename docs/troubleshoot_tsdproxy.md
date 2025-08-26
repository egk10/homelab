# Troubleshooting tsdproxy Tailscale Authentication

## Current Issue
tsdproxy is getting "invalid key: unable to validate API key" errors even with a supposedly reusable auth key.

## Possible Causes

1. **Auth key not actually reusable**
   - Some Tailscale admin consoles don't clearly indicate when a key is single-use vs reusable
   - The key may have been consumed by previous attempts

2. **Auth key expired or revoked**
   - Check if the key is still valid in Tailscale admin console

3. **tsdproxy limitation with tsnet**
   - tsdproxy spawns multiple tsnet instances (one per service)
   - Each instance tries to authenticate, which may consume the key

## Solutions to Try

### Option 1: Generate a fresh reusable auth key
1. Go to https://login.tailscale.com/admin/settings/keys
2. **Revoke** the current key: `tskey-auth-kmDCJkd73m11CNTRL-7WsUnMFuhjMuC5DtL4JxiMiRjYkeUATpZ`
3. Generate a new key with:
   - **Reusable**: YES (very important)
   - **Ephemeral**: YES (nodes will be removed when tsdproxy stops)
   - **Expiry**: Set to 90 days or longer
4. Update both locations:
   ```bash
   # Update auth key file
   echo "YOUR_NEW_REUSABLE_KEY" > tsdproxy/config/authkey
   chmod 600 tsdproxy/config/authkey
   
   # Update docker-compose.yml TAILSCALE_AUTH_KEY environment variable
   # Then restart tsdproxy
   sudo rm -rf tsdproxy/datadir/default/*
   docker compose up -d --no-deps --force-recreate tsdproxy
   ```

### Option 2: Use Caddy for automatic HTTPS (recommended alternative)
If tsdproxy continues to fail, we can use Caddy which provides automatic HTTPS:

```yaml
# Add to docker-compose.yml
caddy:
  image: caddy:2.8-alpine
  container_name: caddy
  ports:
    - "80:80"
    - "443:443"
  volumes:
    - ./caddy/Caddyfile:/etc/caddy/Caddyfile:ro
    - ./caddy/data:/data
    - ./caddy/config:/config
  environment:
    - VAULTWARDEN_DOMAIN=${VAULTWARDEN_DOMAIN}
    - NEXTCLOUD_DOMAIN=${NEXTCLOUD_DOMAIN}
  restart: unless-stopped
  networks:
    - web
```

### Option 3: Check Tailscale admin console
1. Go to https://login.tailscale.com/admin/machines
2. Look for any machines named `immich`, `vaultwarden`, `nextcloud`, `homeassistcanada`
3. If they exist but are offline, delete them
4. Try tsdproxy restart again

## Current Status
- ✅ Immich: 272 photos stored in Ceph
- ✅ Vaultwarden: Secure Argon2 admin token
- ✅ Nextcloud: Installed and running
- ❌ HTTPS access: Blocked by tsdproxy auth issues

## Next Steps
1. Try Option 1 (fresh reusable key) first
2. If that fails, implement Option 2 (Caddy)
3. Once HTTPS is working, test:
   - https://vaultwarden.velociraptor-scylla.ts.net
   - https://nextcloud.velociraptor-scylla.ts.net (for admin user creation)
   - https://immich.velociraptor-scylla.ts.net
