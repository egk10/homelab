VS Code transition guide — open homelab on laptop and pull latest

Goal
- Open the `homelab` project on your laptop from VS Code (Remote-SSH), pull the repo, and enable GitHub Copilot tooling for editing and chat.

Checklist
- [ ] Add an SSH config entry for `laptop.velociraptor-scylla.ts.net` (optional)
- [ ] Install Remote - SSH extension in VS Code
- [ ] Connect to the laptop and open folder `/home/egk/homelab`
- [ ] Run `git pull` and `chmod +x scripts/*.sh`
- [ ] (Optional) Install GitHub Copilot and sign in

Quick steps (copy/paste)

1) (Optional) Add an SSH config entry on your machine that runs VS Code (eliedesk):

```bash
# edit ~/.ssh/config and add:
Host laptop
  HostName laptop.velociraptor-scylla.ts.net
  User egk
  ForwardAgent yes
  IdentityFile ~/.ssh/id_rsa
```

2) Install the Remote-SSH extension in VS Code (if not already installed)
- Open Extensions (Ctrl+Shift+X) → search `Remote - SSH` → Install

3) Remote-SSH connect to laptop and open folder
- Command Palette (Ctrl+Shift+P) → `Remote-SSH: Connect to Host...` → choose `laptop` (or paste full hostname)
- When connected: File → Open Folder → `/home/egk/homelab`

4) Pull latest repo and prepare scripts (in the VS Code terminal on the laptop)

```bash
cd /home/egk/homelab
git pull origin main
chmod +x scripts/*.sh || true
```

5) Install or enable GitHub Copilot in VS Code
- In Extensions view, install `GitHub Copilot` (and `GitHub Copilot Chat` if you use chat features)
- Sign in when prompted (use the browser-based OAuth flow)
- Optional settings: enable inline suggestions and enable Copilot Chat in the sidebar

6) Quick Git/Copilot workflow tips
- Use the Source Control view to stage/commit/push changes
- Use Copilot inline suggestions (accept with Tab) and Copilot Chat (open the Chat view) to ask for edits, generate commits, or create PR text

7) Run tests / deploy commands from the VS Code terminal
- Mount CephFS (if needed): `sudo ./scripts/mount_cephfs_example.sh`
- Create RGW users (if on admin node): `./scripts/create_rgw_user_and_bucket.sh --uid immich --bucket immich`
- Start services: `docker compose up -d` (or start specific services)

Notes & troubleshooting
- If Remote-SSH can't connect: ensure `ssh laptop` works from eliedesk terminal and that the Remote-SSH extension can use the same SSH config.
- If GitHub Copilot requires a subscription, sign in with the GitHub account that has access.
- Keep secrets out of the repo: edit `.env` locally on the laptop and do not commit it.

If you want, I can also create a small VS Code `tasks.json` that runs `git pull` and `docker compose up -d` from the laptop workspace. Say "create tasks" and I'll add it.
