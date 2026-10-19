# Immich reliability monitor

The monitor is staged for both the workstation and minitx. It checks Cloudvero over the existing `cloudvero` SSH alias. The workstation reads minitx worker evidence over SSH; minitx reads its local worker evidence, so it remains useful while the desktop is off. Ordinary mode makes no production changes.

Run a read-only check with:

```sh
python3 /home/egk/homelab/reliability/monitor/immich_monitor.py
```

It checks the Immich version and ping API, service and container state, the bind mount from `/var/lib/immich/data` to Immich's upload root, ext4 filesystem type, the local upload marker, aggregate counts for recently created user assets, and at least 20 GiB free on the Cloudvero media filesystem and the current backup worker's filesystem. Aggregate activity excludes the dedicated monitor user, so its synthetic assets never look like mobile uploads. Ceph health is informational because Ceph is no longer the Immich primary storage path. Zero recent user uploads remain informational while the phones are being recovered.

Backup health accepts the newest complete evidence set from either worker, provided its manifest, report, required repositories, and role-specific restore proofs agree. A valid media backup must be no older than 2 hours, include successful snapshots for every repository declared in that manifest's `required_repositories`, report zero integrity errors, and reconcile `verified + missing = assets`. The monitor reads the minitx files `/home/egk/.local/state/immich-backup/last-media.json`, `last-report-media.json`, `last-attempt.json`, `last-restore-media.json`, and `last-restore-media-ceph.json` over SSH from the workstation. The minitx monitor reads those files locally. Workstation evidence pairs workstation-local and minitx-secondary restores; minitx evidence pairs minitx-local and Ceph restores. Each restore proof must match the same worker/host, required-repository set, and be no older than 35 days. A failed attempt on the selected worker prevents it from satisfying coverage; another worker can still provide a valid coverage set, while the failed worker remains visible as degraded. Ceph copy health is informational for application availability, while each worker's declared required repositories determine backup coverage.

Cached media and current source-media evidence use separate dynamic baselines. The first fresh, internally consistent backup establishes each baseline; later counts may stay level or decrease, and increases are flagged. This keeps a recoverable workstation cache from masking an original that disappeared from Cloudvero. No historical count is hard coded because phone recovery can change the baseline. Source or cached hash mismatches and other integrity errors always fail. A recoverable cached copy is reported separately as useful recovery capacity.

Every check atomically updates `state.json` and appends a record to `events.jsonl`. The local journal receives an error or recovery notice when the aggregate state changes. The state directory and events file are private to `egk`; the API key is never copied into monitor state, output, or the journal.

## Synthetic end-to-end check

Run manually only after the storage migration is ready:

```sh
python3 /home/egk/homelab/reliability/monitor/immich_monitor.py --synthetic
```

The operation requires the root operator to confirm that the first complete three-repository media backup has finished, the dedicated API key at `/home/egk/.local/state/immich-monitor/api-key` with owner-only permissions, and a readiness gate at `/home/egk/.local/state/immich-monitor/media-ready` whose exact contents are `ready`. The remote preflight must also confirm that the ext4 `/var/lib/immich/data` directory is bind-mounted as Immich's upload root and contains the upload marker. No synthetic flow is run until these conditions hold.

The key is checked through `GET /api/api-keys/me` and must have exactly `asset.upload`, `asset.download`, and `asset.delete`. The key itself is read only into memory. The script creates a unique, randomized 16×16 PNG, sends its SHA-1 in `x-immich-checksum`, and accepts only HTTP 201 with `status=created`. It downloads `/api/assets/{id}/original` and compares SHA-1, invokes the existing media backup script, confirms the created ID and checksum in the selected worker's required backup repositories, and records any post-upload Ceph snapshot ID when the optional third copy succeeds. It then restores the exact local snapshot ID written to its private run state. After confirming that same ID/checksum in the restored inventory, it removes only that test's private restore directory under `/home/egk/immich-restore-*`. After deleting only the returned synthetic Immich ID, it waits for a read-only Cloudvero query to confirm the database row and original file are both absent; an API delete response alone does not complete the flow. Root can use the private `ceph_snapshot_id`, `asset_id`, `sha1`, and `original_path` in the local synthetic state to read the preserved Ceph snapshot after the live asset is gone.

An upload response marked duplicate is retained as a duplicate and never deleted. A network-ambiguous upload is recorded as `upload_inflight` and requires manual review; the script will not retry it or guess an asset ID. If backup is locked or fails, it records `backup_pending`, exits unsuccessfully, retains the synthetic asset, and resumes on the next scheduled attempt without uploading another asset. Before deleting the synthetic original, cleanup acquires the workstation backup lock and holds the minitx backup lock over SSH. Both locks stay held until the read-only database and source-file absence checks pass. If either lock is busy or unreachable, cleanup remains pending and retries without uploading another asset; this prevents a source inventory from racing the synthetic deletion. Cleanup runs only after live readback, fresh media backup, and restore SHA-1 verification all pass. The synthetic asset ID and flow phase are stored only in the owner-only local state file.

No email, WhatsApp, or other external notification is sent. This E2E includes a full media backup and isolated restore, so it is scheduled daily at 06:15 only after root sets the readiness gate and enables the workstation timer. The timer skips missed runs while the workstation is off, avoiding a catch-up E2E after the daily check already ran. Ordinary checks run every 15 minutes on both workstation and minitx. The backup worker timers are staged by the backup implementation: minitx at :15 and workstation standby at :45 each hour.

## Timer staging

`immich-monitor.service` and `.timer` stage workstation checks; `immich-monitor-minitx.service` and `.timer` stage local checks on minitx; `immich-synthetic.service` and `.timer` stage the gated workstation E2E. None is installed or enabled by this change. Root installs the user units on each host after review. The synthetic timer must remain disabled until root sets the ready marker.

The E2E may take several hours and shares the backup script's lock. A lock conflict or failed backup exits nonzero; the systemd service retries later and never reports success without fresh backup and restore evidence.
