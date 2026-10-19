#!/usr/bin/env python3
"""Read-only Immich and completed database-backup monitor for Cloudvero."""

from __future__ import annotations

import datetime as dt
import argparse
import csv
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import selectors
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import zlib


ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "state.json"
EVENTS_FILE = ROOT / "events.jsonl"
BASE_URL = os.environ.get(
    "IMMICH_URL", "https://immich.velociraptor-scylla.ts.net"
).rstrip("/")
SSH_HOST = os.environ.get("IMMICH_SSH_HOST", "cloudvero")
MAX_BACKUP_AGE = int(os.environ.get("IMMICH_BACKUP_MAX_AGE_HOURS", "2")) * 3600
HTTP_TIMEOUT = 8
SSH_TIMEOUT = 18
STATE_DIR = Path("/home/egk/.local/state/immich-monitor")
API_KEY_FILE = STATE_DIR / "api-key"
MEDIA_READY_FILE = STATE_DIR / "media-ready"
BACKUP_STATE_DIR = Path("/home/egk/.local/state/immich-backup")
MEDIA_BACKUP_STATE = BACKUP_STATE_DIR / "last-media.json"
MEDIA_BACKUP_REPORT_STATE = BACKUP_STATE_DIR / "last-report-media.json"
MEDIA_RESTORE_STATE = BACKUP_STATE_DIR / "last-restore-media.json"
MEDIA_RESTORE_SECONDARY_STATE = BACKUP_STATE_DIR / "last-restore-media-secondary.json"
MEDIA_BACKUP_ATTEMPT_STATE = BACKUP_STATE_DIR / "last-attempt.json"
BACKUP_SCRIPT = Path("/home/egk/homelab/reliability/backup/immich_backup.py")
RESTORE_SCRIPT = Path("/home/egk/homelab/reliability/backup/immich_restore_test.py")
MEDIA_BACKUP_STAGE = Path("/home/egk/immich-backup-staging/media")
MEDIA_RESTORE_MAX_AGE = int(os.environ.get("IMMICH_MEDIA_RESTORE_MAX_AGE_DAYS", "35")) * 86400
MEDIA_BASELINE_FILE = STATE_DIR / "media-integrity-baseline.json"
SOURCE_BASELINE_FILE = STATE_DIR / "primary-source-missing-baseline.json"
MIN_FREE_BYTES = int(os.environ.get("IMMICH_MIN_FREE_GIB", "20")) * 1024**3
WORKER_BACKUP_HOST = os.environ.get("IMMICH_WORKER_BACKUP_HOST", "minitx")
WORKER_STATE_DIR = Path("/home/egk/.local/state/immich-backup")
REMOTE_WORKER_EVIDENCE = r'''python3 - <<'PY'
import json
from pathlib import Path
root = Path('/home/egk/.local/state/immich-backup')
names = ('last-media.json', 'last-report-media.json', 'last-attempt.json',
         'last-restore-media.json', 'last-restore-media-ceph.json')
data = {}
for name in names:
    try:
        data[name] = json.loads((root / name).read_text())
    except (OSError, ValueError):
        data[name] = None
print(json.dumps(data, separators=(',', ':')))
PY
'''


REMOTE_READONLY = r'''set +e
printf 'service_immich=%s\n' "$(systemctl is-active homelab-immich.service 2>/dev/null || true)"
for c in immich_server immich_postgres immich_redis; do
  state=$(docker inspect --format '{{.State.Status}}' "$c" 2>/dev/null || printf absent)
  printf 'container_%s=%s\n' "$c" "$state"
done
source=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/usr/src/app/upload"}}{{.Source}}{{end}}{{end}}' immich_server 2>/dev/null)
filesystem=$(findmnt -n -o FSTYPE -T /var/lib/immich/data 2>/dev/null)
if [ "$source" = '/var/lib/immich/data' ] && [ "$filesystem" = 'ext4' ] && test -r /var/lib/immich/data/upload/.immich; then
  printf 'media_source_ready=yes\n'
else
  printf 'media_source_ready=no\n'
fi
source_free=$(df -B1 --output=avail /var/lib/immich/data 2>/dev/null | tail -1 | tr -d ' ')
printf 'source_free_bytes=%s\n' "${source_free:-0}"
asset_stats=$(docker exec immich_postgres psql -U immich -d immich -AtF '|' -c 'SELECT count(*) FILTER (WHERE "createdAt" > now() - interval '\''24 hours'\''), count(*) FILTER (WHERE "createdAt" > now() - interval '\''7 days'\''), COALESCE(extract(epoch from max("createdAt"))::bigint::text, '\'''\'') FROM asset WHERE "deletedAt" IS NULL AND "ownerId" NOT IN (SELECT id FROM "user" WHERE email = '\''immich-monitor@homelab.invalid'\'');' 2>/dev/null)
if [ -n "$asset_stats" ]; then
  IFS='|' read -r assets_24h assets_7d last_asset_epoch <<EOF
$asset_stats
EOF
  printf 'assets_24h=%s\nassets_7d=%s\nlast_asset_epoch=%s\n' "$assets_24h" "$assets_7d" "$last_asset_epoch"
else
  printf 'assets_24h=unknown\nassets_7d=unknown\nlast_asset_epoch=\n'
fi
if docker ps --format '{{.Names}}' | grep -Eq '^immich_machine_learning$|^immich_ml$'; then
  printf 'machine_learning=present\n'
else
  printf 'machine_learning=absent\n'
fi
'''

REMOTE_CEPH_READONLY = r'''set +e
if command -v cephadm >/dev/null 2>&1; then
  timeout 5s sudo -n cephadm shell -- ceph health 2>/dev/null | head -c 40
elif command -v ceph >/dev/null 2>&1; then
  timeout 5s ceph health 2>/dev/null | head -c 40
else
  printf 'not-installed'
fi
'''


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
        os.chmod(path, 0o600)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


@contextmanager
def monitor_lock():
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = (STATE_DIR / "monitor.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def get_json(path: str) -> tuple[int, object]:
    request = urllib.request.Request(f"{BASE_URL}/api/{path}", headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def parse_remote(output: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)


def read_ceph_health() -> str:
    """Best-effort informational probe; Ceph must not gate Immich health."""
    try:
        completed = subprocess.run(
            ["ssh", "-F", "/dev/null", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4", SSH_HOST,
             "bash", "-s"],
            input=REMOTE_CEPH_READONLY,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=9,
            check=False,
        )
        health = completed.stdout.strip()[:40]
        return health if completed.returncode == 0 and health else "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def read_object(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def update_missing_baseline(backup: dict[str, object] | None, now: dt.datetime) -> int:
    if not backup:
        current = read_object(MEDIA_BASELINE_FILE)
        return int(current.get("known_missing", -1)) if current else -1
    try:
        created = float(backup.get("created_at", 0))
        assets = int(backup.get("assets", -1))
        verified = int(backup.get("verified", -1))
        missing = int(backup.get("missing", -1))
        errors = int(backup.get("integrity_errors", -1))
        snapshots = backup.get("snapshots", [])
        required = backup.get("required_repositories", [])
    except (TypeError, ValueError):
        current = read_object(MEDIA_BASELINE_FILE)
        return int(current.get("known_missing", -1)) if current else -1
    if (
        backup.get("kind") != "media"
        or created <= 0
        or now.timestamp() - created > MAX_BACKUP_AGE
        or assets < 0
        or verified < 0
        or missing < 0
        or verified + missing != assets
        or errors != 0
        or not isinstance(snapshots, list)
        or not isinstance(required, list)
        or not required
        or not all(
            any(isinstance(item, dict) and item.get("repository") == repo and item.get("status") == "ok"
                for item in snapshots)
            for repo in required
        )
    ):
        current = read_object(MEDIA_BASELINE_FILE)
        return int(current.get("known_missing", -1)) if current else -1
    current = read_object(MEDIA_BASELINE_FILE)
    old_missing = int(current.get("known_missing", -1)) if current else -1
    if old_missing < 0 or missing < old_missing:
        atomic_json(MEDIA_BASELINE_FILE, {
            "known_missing": missing,
            "established_at": now.isoformat(timespec="seconds"),
            "source_backup_created_at": created,
        })
        return missing
    return old_missing


def update_source_missing_baseline(backup: dict[str, object] | None, now: dt.datetime) -> int:
    if not backup:
        current = read_object(SOURCE_BASELINE_FILE)
        return int(current.get("source_missing", -1)) if current else -1
    try:
        created = float(backup.get("source_checked_at", backup.get("created_at", 0)))
        missing = int(backup.get("source_missing", -1))
        errors = int(backup.get("source_integrity_errors", -1))
    except (TypeError, ValueError):
        current = read_object(SOURCE_BASELINE_FILE)
        return int(current.get("source_missing", -1)) if current else -1
    if (backup.get("kind") != "media" or created <= 0 or now.timestamp() - created > MAX_BACKUP_AGE
            or missing < 0 or errors != 0):
        current = read_object(SOURCE_BASELINE_FILE)
        return int(current.get("source_missing", -1)) if current else -1
    current = read_object(SOURCE_BASELINE_FILE)
    old_missing = int(current.get("source_missing", -1)) if current else -1
    if old_missing < 0 or missing < old_missing:
        atomic_json(SOURCE_BASELINE_FILE, {
            "source_missing": missing,
            "established_at": now.isoformat(timespec="seconds"),
            "source_backup_created_at": created,
        })
        return missing
    return old_missing


def worker_evidence() -> tuple[dict[str, object] | None, bool]:
    """Read the minitx report locally on the worker or over SSH on workstation."""
    local_host = socket.gethostname().split(".", 1)[0]
    if local_host == "minitx" or WORKER_BACKUP_HOST in ("local", "localhost"):
        value = {
            "last-media.json": read_object(WORKER_STATE_DIR / "last-media.json"),
            "last-report-media.json": read_object(WORKER_STATE_DIR / "last-report-media.json"),
            "last-attempt.json": read_object(WORKER_STATE_DIR / "last-attempt.json"),
            "last-restore-media.json": read_object(WORKER_STATE_DIR / "last-restore-media.json"),
            "last-restore-media-ceph.json": read_object(WORKER_STATE_DIR / "last-restore-media-ceph.json"),
        }
        return value, bool(value["last-media.json"] and value["last-report-media.json"])
    try:
        completed = subprocess.run(
            ["ssh", "-F", "/dev/null", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", WORKER_BACKUP_HOST, "bash", "-s"],
            input=REMOTE_WORKER_EVIDENCE,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=12,
            check=False,
        )
        if completed.returncode != 0:
            mirror = {
                source: read_object(BACKUP_STATE_DIR / f"minitx-{source}")
                for source in (
                    "last-media.json", "last-report-media.json", "last-attempt.json",
                    "last-restore-media.json", "last-restore-media-ceph.json",
                )
            }
            return (mirror if mirror.get("last-media.json") else None), False
        value = json.loads(completed.stdout)
        available = isinstance(value, dict) and bool(value.get("last-media.json") and value.get("last-report-media.json"))
        return (value if isinstance(value, dict) else None), available
    except (OSError, subprocess.TimeoutExpired, ValueError):
        mirror = {
            source: read_object(BACKUP_STATE_DIR / f"minitx-{source}")
            for source in (
                "last-media.json", "last-report-media.json", "last-attempt.json",
                "last-restore-media.json", "last-restore-media-ceph.json",
            )
        }
        return (mirror if mirror.get("last-media.json") else None), False


def restore_proof_valid(
    proof: dict[str, object] | None, *, worker: str, backup: dict[str, object],
    repository: str, now: dt.datetime,
) -> bool:
    if not proof or proof.get("kind") != "media" or proof.get("database_restored") is not True:
        return False
    required = backup.get("required_repositories")
    if not isinstance(required, list) or proof.get("worker") != worker:
        return False
    backup_host = str(backup.get("worker_host", ""))
    if not backup_host or proof.get("worker_host") != backup_host:
        return False
    if proof.get("required_repositories") != required or proof.get("repository") != repository:
        return False
    try:
        tested_at = float(proof.get("tested_at", 0))
        assets = int(proof.get("asset_count", -1))
        verified = int(proof.get("originals_verified", -1))
        missing = int(proof.get("known_missing", -1))
    except (TypeError, ValueError):
        return False
    return (
        0 <= now.timestamp() - tested_at <= MEDIA_RESTORE_MAX_AGE
        and assets >= 0 and verified >= 0 and missing >= 0
        and verified + missing == assets and bool(proof.get("snapshot_id"))
    )


def local_media_evidence(now: dt.datetime) -> tuple[dict[str, bool], dict[str, object]]:
    checks: dict[str, bool] = {}
    observations: dict[str, object] = {}
    workstation_backup = read_object(MEDIA_BACKUP_STATE)
    workstation_report = read_object(MEDIA_BACKUP_REPORT_STATE)
    workstation_attempt = read_object(MEDIA_BACKUP_ATTEMPT_STATE)
    worker_data, worker_probe_ok = worker_evidence()
    current_host = socket.gethostname().split(".", 1)[0]
    if current_host == "minitx":
        workstation_backup = workstation_report = workstation_attempt = None
    worker_backup = worker_data.get("last-media.json") if worker_data else None
    worker_report = worker_data.get("last-report-media.json") if worker_data else None
    worker_attempt = worker_data.get("last-attempt.json") if worker_data else None
    candidates: list[tuple[str, dict[str, object], dict[str, object] | None,
                           dict[str, object] | None, dict[str, object] | None,
                           dict[str, object] | None]] = []
    for host, candidate, candidate_report, candidate_attempt in (
        ("workstation", workstation_backup, workstation_report, workstation_attempt),
        ("minitx", worker_backup, worker_report, worker_attempt),
    ):
        if isinstance(candidate, dict) and candidate.get("kind") == "media":
            if host == "minitx":
                restore_a = worker_data.get("last-restore-media.json") if worker_data else None
                restore_b = worker_data.get("last-restore-media-ceph.json") if worker_data else None
            else:
                restore_a = read_object(MEDIA_RESTORE_STATE)
                restore_b = read_object(MEDIA_RESTORE_SECONDARY_STATE)
            candidates.append((host, candidate,
                               candidate_report if isinstance(candidate_report, dict) else None,
                               candidate_attempt if isinstance(candidate_attempt, dict) else None,
                               restore_a if isinstance(restore_a, dict) else None,
                               restore_b if isinstance(restore_b, dict) else None))

    def candidate_valid(item: tuple[str, dict[str, object], dict[str, object] | None,
                                      dict[str, object] | None, dict[str, object] | None,
                                      dict[str, object] | None]) -> bool:
        host, candidate, candidate_report, candidate_attempt, proof_a, proof_b = item
        required = candidate.get("required_repositories")
        rows = candidate_report.get("repository_status", []) if candidate_report else []
        repo_map = {str(row.get("repository")): row for row in rows
                    if isinstance(row, dict) and row.get("repository")} if isinstance(rows, list) else {}
        snapshots = candidate.get("snapshots", [])
        if not isinstance(required, list) or not required or not candidate_report:
            return False
        if (candidate_report.get("kind") != "media"
                or candidate_report.get("worker") != candidate.get("worker")
                or candidate_report.get("worker_host") != candidate.get("worker_host")
                or candidate_report.get("required_repositories") != required):
            return False
        if candidate_report.get("mandatory_repositories_healthy") is not True:
            return False
        if (candidate_attempt and candidate_attempt.get("kind") == "media"
                and candidate_attempt.get("status") == "failed"
                and float(candidate_attempt.get("completed_at", 0) or 0) > float(candidate.get("created_at", 0) or 0)):
            return False
        if not all(repo_map.get(str(repo), {}).get("status") == "ok" for repo in required):
            return False
        if not isinstance(snapshots, list) or not all(
            any(isinstance(row, dict) and row.get("repository") == repo and row.get("status") == "ok"
                for row in snapshots) for repo in required
        ):
            return False
        primary_repo, secondary_repo = required[0], required[1] if len(required) > 1 else ""
        return (
            restore_proof_valid(proof_a, worker=str(candidate.get("worker")), backup=candidate,
                                repository=str(primary_repo), now=now)
            and restore_proof_valid(proof_b, worker=str(candidate.get("worker")), backup=candidate,
                                    repository=str(secondary_repo), now=now)
        )

    candidates.sort(key=lambda item: float(item[1].get("created_at", 0) or 0), reverse=True)
    valid_candidates = [item for item in candidates if candidate_valid(item)]
    if valid_candidates:
        backup_host, backup, report, attempt, restore, restore_secondary = valid_candidates[0]
    elif candidates:
        backup_host, backup, report, attempt, restore, restore_secondary = candidates[0]
    else:
        backup_host, backup, report, attempt, restore, restore_secondary = "unknown", None, None, None, None, None

    source_candidates: list[tuple[float, str, dict[str, object]]] = []
    for host, item_backup, item_report in (
        ("workstation", workstation_backup, workstation_report),
        ("minitx", worker_backup, worker_report),
    ):
        for item in (item_backup, item_report):
            if isinstance(item, dict) and item.get("kind") == "media" and "source_missing" in item:
                try:
                    checked = float(item.get("source_checked_at", item.get("created_at", 0)) or 0)
                except (TypeError, ValueError):
                    checked = 0
                source_candidates.append((checked, host, item))
    source_candidates.sort(
        key=lambda row: (row[0], int(float(row[2].get("source_integrity_errors", 0) or 0) > 0)),
        reverse=True,
    )
    source_checked_at, source_worker, source_data = (
        source_candidates[0] if source_candidates else (0, "unknown", None)
    )

    backup_created = float(backup.get("created_at", 0)) if backup else 0
    backup_age = max(0, int(now.timestamp() - backup_created)) if backup_created else None
    backup_assets = int(backup.get("assets", -1)) if backup else -1
    backup_verified = int(backup.get("verified", -1)) if backup else -1
    backup_missing = int(backup.get("missing", -1)) if backup else -1
    backup_errors = int(backup.get("integrity_errors", -1)) if backup else -1
    snapshots = backup.get("snapshots", []) if backup else []
    repository_status = report.get("repository_status", []) if report else []
    repo_by_name = {
        str(item.get("repository")): item
        for item in repository_status
        if isinstance(item, dict) and item.get("repository")
    } if isinstance(repository_status, list) else {}
    required_repositories = backup.get("required_repositories", []) if backup else []
    required_repositories_valid = isinstance(required_repositories, list) and bool(required_repositories)
    mandatory_ok = required_repositories_valid and all(
        repo_by_name.get(str(name), {}).get("status") == "ok" for name in required_repositories
    )
    mini_statuses = worker_report.get("repository_status", []) if worker_report else []
    mini_repo_map = {
        str(item.get("repository")): item
        for item in mini_statuses
        if isinstance(item, dict) and item.get("repository")
    } if isinstance(mini_statuses, list) else {}
    ceph_report = mini_repo_map.get(
        "s3:http://127.0.0.1:17480/immich-backups",
        repo_by_name.get("s3:http://127.0.0.1:17480/immich-backups", {}),
    )
    ceph_backup_status = ceph_report.get("status", "unknown")
    cluster_copy_degraded = (
        bool(worker_report.get("cluster_copy_degraded", False)) if worker_report
        else bool(report.get("cluster_copy_degraded", False)) if report else False
    ) or ceph_backup_status == "failed"
    baseline_missing = update_missing_baseline(backup, now)
    source_missing = int(source_data.get("source_missing", -1)) if source_data else -1
    source_errors = int(source_data.get("source_integrity_errors", -1)) if source_data else -1
    source_baseline = update_source_missing_baseline(source_data, now)
    counts_valid = (
        backup is not None
        and backup_assets >= 0
        and backup_verified >= 0
        and backup_missing >= 0
        and backup_verified + backup_missing == backup_assets
        and backup_errors == 0
    )
    observations.update({
        "media_backup_created_at": backup_created or None,
        "media_backup_age_seconds": backup_age,
        "media_backup_assets": backup_assets if backup else None,
        "media_backup_sha1_verified": backup_verified if backup else None,
        "media_backup_known_missing": backup_missing if backup else None,
        "media_backup_missing_baseline": baseline_missing if baseline_missing >= 0 else None,
        "primary_source_missing": source_missing if source_data else None,
        "primary_source_verified": source_data.get("source_verified") if source_data else None,
        "primary_source_present": source_data.get("source_present") if source_data else None,
        "primary_source_missing_baseline": source_baseline if source_baseline >= 0 else None,
        "primary_source_integrity_errors": source_errors if source_data else None,
        "primary_inventory_complete_reported": source_data.get("primary_inventory_complete") if source_data else None,
        "primary_source_checked_at": source_checked_at or None,
        "primary_source_report_worker": source_worker,
        "cached_recovery_available": backup.get("cache_recovery_available") if backup else None,
        "media_backup_integrity_errors": backup_errors if backup else None,
        "media_backup_snapshot_count": len(snapshots) if isinstance(snapshots, list) else 0,
        "media_backup_worker": backup_host,
        "media_backup_required_repositories": required_repositories if required_repositories_valid else [],
        "mandatory_repositories_healthy": mandatory_ok,
        "ceph_backup_copy_status": ceph_backup_status,
        "cluster_copy_degraded": cluster_copy_degraded,
        "minitx_worker_report_available": worker_probe_ok,
    })
    checks["media_backup_exists"] = backup is not None and backup.get("kind") == "media"
    checks["media_backup_fresh"] = backup_age is not None and backup_age <= MAX_BACKUP_AGE
    checks["media_backup_required_snapshots"] = (
        required_repositories_valid
        and isinstance(snapshots, list)
        and all(
            any(isinstance(item, dict) and item.get("repository") == repo and item.get("status") == "ok"
                for item in snapshots)
            for repo in required_repositories
        )
    )
    checks["media_backup_repository_report"] = (
        report is not None
        and report.get("kind") == "media"
        and report.get("worker") == backup.get("worker")
        and report.get("worker_host") == backup.get("worker_host")
        and report.get("required_repositories") == required_repositories
    )
    checks["media_backup_mandatory_repositories"] = (
        required_repositories_valid and mandatory_ok
        and report is not None and report.get("mandatory_repositories_healthy") is True
    )
    checks["media_backup_integrity_counts"] = (
        counts_valid
    )
    checks["media_backup_missing_not_increased"] = (
        counts_valid and baseline_missing >= 0 and backup_missing <= baseline_missing
    )
    checks["primary_source_report_fresh"] = (
        source_data is not None and source_checked_at > 0
        and now.timestamp() - source_checked_at <= MAX_BACKUP_AGE
    )
    checks["primary_source_integrity_errors_zero"] = source_data is not None and source_errors == 0
    checks["primary_source_missing_not_increased"] = (
        source_data is not None and source_missing >= 0
        and source_baseline >= 0 and source_missing <= source_baseline
    )
    failed_media_attempt = (
        isinstance(attempt, dict)
        and attempt.get("kind") == "media"
        and attempt.get("status") == "failed"
        and float(attempt.get("completed_at", 0) or 0) > backup_created
    )
    checks["media_backup_last_attempt_ok"] = not failed_media_attempt
    checks["media_backup_selected_worker_evidence_valid"] = bool(valid_candidates)
    observations["media_backup_last_attempt_status"] = {
        "workstation": workstation_attempt.get("status") if workstation_attempt else None,
        "minitx": worker_attempt.get("status") if worker_attempt else None,
    }
    worker_degraded: dict[str, bool] = {}
    for host, candidate, candidate_report, candidate_attempt, _, _ in candidates:
        attempt_failed = bool(
            candidate_attempt and candidate_attempt.get("kind") == "media"
            and candidate_attempt.get("status") == "failed"
            and float(candidate_attempt.get("completed_at", 0) or 0) > float(candidate.get("created_at", 0) or 0)
        )
        required = candidate.get("required_repositories", [])
        rows = candidate_report.get("repository_status", []) if candidate_report else []
        repo_map = {str(row.get("repository")): row for row in rows
                    if isinstance(row, dict) and row.get("repository")} if isinstance(rows, list) else {}
        repo_failed = bool(required) and any(repo_map.get(str(repo), {}).get("status") != "ok" for repo in required)
        worker_degraded[host] = attempt_failed or repo_failed
    observations["media_backup_worker_degraded"] = worker_degraded
    if current_host != "minitx" and not worker_probe_ok:
        observations["media_backup_worker_degraded"]["minitx_report_unreachable"] = True

    restore_time = float(restore.get("tested_at", 0)) if restore else 0
    restore_age = max(0, int(now.timestamp() - restore_time)) if restore_time else None
    restore_assets = int(restore.get("asset_count", -1)) if restore else -1
    restore_verified = int(restore.get("originals_verified", -1)) if restore else -1
    restore_missing = int(restore.get("known_missing", -1)) if restore else -1
    observations.update({
        "media_restore_tested_at": restore_time or None,
        "media_restore_age_seconds": restore_age,
        "media_restore_asset_count": restore_assets if restore else None,
        "media_restore_sha1_verified": restore_verified if restore else None,
        "media_restore_known_missing": restore_missing if restore else None,
        "media_restore_secondary_tested_at": restore_secondary.get("tested_at") if restore_secondary else None,
        "media_restore_secondary_sha1_verified": restore_secondary.get("originals_verified") if restore_secondary else None,
        "media_restore_secondary_known_missing": restore_secondary.get("known_missing") if restore_secondary else None,
    })
    checks["media_restore_exists"] = restore is not None and restore.get("kind") == "media" and restore.get("database_restored") is True
    checks["media_restore_fresh"] = restore_age is not None and restore_age <= MEDIA_RESTORE_MAX_AGE
    checks["media_restore_counts_consistent"] = (
        restore is not None
        and restore_assets >= 0
        and restore_verified >= 0
        and restore_missing >= 0
        and restore_verified + restore_missing == restore_assets
        and bool(restore.get("snapshot_id"))
    )
    secondary_time = float(restore_secondary.get("tested_at", 0)) if restore_secondary else 0
    secondary_age = max(0, int(now.timestamp() - secondary_time)) if secondary_time else None
    secondary_assets = int(restore_secondary.get("asset_count", -1)) if restore_secondary else -1
    secondary_verified = int(restore_secondary.get("originals_verified", -1)) if restore_secondary else -1
    secondary_missing = int(restore_secondary.get("known_missing", -1)) if restore_secondary else -1
    observations["media_restore_secondary_age_seconds"] = secondary_age
    checks["media_restore_secondary_exists"] = (
        restore_secondary is not None
        and restore_secondary.get("kind") == "media"
        and restore_secondary.get("database_restored") is True
        and bool(restore_secondary.get("snapshot_id"))
    )
    checks["media_restore_secondary_fresh"] = secondary_age is not None and secondary_age <= MEDIA_RESTORE_MAX_AGE
    checks["media_restore_secondary_counts_consistent"] = (
        restore_secondary is not None
        and secondary_assets >= 0
        and secondary_verified >= 0
        and secondary_missing >= 0
        and secondary_verified + secondary_missing == secondary_assets
    )
    observations["media_restore_proof_a_repository"] = restore.get("repository") if restore else None
    observations["media_restore_proof_b_repository"] = restore_secondary.get("repository") if restore_secondary else None
    return checks, observations


def save_state_synthetic(synthetic: dict[str, object]) -> None:
    with monitor_lock():
        previous = read_object(STATE_FILE) or {}
        previous["synthetic"] = synthetic
        atomic_json(STATE_FILE, previous)


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def make_synthetic_png(asset_uuid: str) -> bytes:
    width = height = 16
    pixels = b"".join(b"\x00" + secrets.token_bytes(width * 3) for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    metadata = b"ImmichMonitor\x00" + asset_uuid.encode("ascii")
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", header)
        + png_chunk(b"tEXt", metadata)
        + png_chunk(b"IDAT", zlib.compress(pixels))
        + png_chunk(b"IEND", b"")
    )


def read_api_key() -> str:
    info = API_KEY_FILE.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError("api_key_file_permissions_invalid")
    key = API_KEY_FILE.read_text(encoding="utf-8").strip()
    if not key or "\n" in key:
        raise RuntimeError("api_key_file_empty_or_invalid")
    return key


def api_request(path: str, *, key: str | None = None, method: str | None = None,
                body: bytes | None = None, content_type: str | None = None,
                timeout: int = HTTP_TIMEOUT) -> tuple[int, bytes]:
    headers = {"Accept": "application/json"}
    if key is not None:
        headers["x-api-key"] = key
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(
        f"{BASE_URL}/api/{path}", data=body, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"api_http_{error.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise RuntimeError(f"api_transport_{type(error).__name__}") from None


def synthetic_server_major() -> int:
    try:
        status, body = api_request("server/version")
        version = json.loads(body.decode("utf-8"))
        major = version.get("major") if isinstance(version, dict) else None
        if status != 200 or type(major) is not int or major < 2:
            raise ValueError("unsupported_or_unknown_version")
        return major
    except (RuntimeError, ValueError, UnicodeError):
        raise RuntimeError("synthetic_server_version_unavailable") from None


def upload_multipart(key: str, asset_uuid: str, payload: bytes, checksum: str,
                     *, server_major: int) -> tuple[int, dict[str, object]]:
    if type(server_major) is not int or server_major < 2:
        raise RuntimeError("synthetic_server_version_unavailable")
    boundary = "immich-monitor-" + uuid.uuid4().hex
    created = dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    fields = {
        "fileCreatedAt": created,
        "fileModifiedAt": created,
    }
    if server_major == 2:
        fields.update({
            "deviceAssetId": "immich-monitor-" + asset_uuid,
            "deviceId": "immich-reliability-monitor",
        })
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
        )
    chunks.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"assetData\"; filename=\"immich-monitor-{asset_uuid}.png\"\r\nContent-Type: image/png\r\n\r\n".encode()
        + payload + b"\r\n"
    )
    chunks.append(f"--{boundary}--\r\n".encode())
    request = urllib.request.Request(
        f"{BASE_URL}/api/assets",
        data=b"".join(chunks),
        headers={
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "x-api-key": key,
            "x-immich-checksum": checksum,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"api_upload_http_{error.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        raise RuntimeError(f"api_upload_{type(error).__name__}") from None


def verify_synthetic_key_scopes(key: str) -> None:
    status, body = api_request("api-keys/me", key=key)
    if status != 200:
        raise RuntimeError("synthetic_api_key_metadata_unavailable")
    try:
        permissions = set(json.loads(body.decode("utf-8")).get("permissions", []))
    except (ValueError, AttributeError, TypeError):
        raise RuntimeError("synthetic_api_key_permissions_unreadable") from None
    required = {"asset.upload", "asset.download", "asset.delete"}
    if permissions != required:
        raise RuntimeError("synthetic_api_key_scope_mismatch")


def find_inventory_rows(directory: Path, asset_id: str) -> tuple[dict[str, str], dict[str, object]]:
    csv_paths = list(directory.rglob("assets.csv"))
    integrity_paths = list(directory.rglob("asset-integrity.json"))
    if len(csv_paths) != 1 or len(integrity_paths) != 1:
        raise RuntimeError("backup_inventory_missing_or_ambiguous")
    with csv_paths[0].open(newline="", encoding="utf-8") as source:
        rows = [row for row in csv.DictReader(source) if row.get("id") == asset_id]
    integrity = json.loads(integrity_paths[0].read_text(encoding="utf-8"))
    matches = [row for row in integrity if row.get("id") == asset_id]
    if len(rows) != 1 or len(matches) != 1:
        raise RuntimeError("synthetic_asset_missing_from_backup_inventory")
    return rows[0], matches[0]


def local_snapshot_id(backup: dict[str, object]) -> str:
    required = backup.get("required_repositories", [])
    snapshots = backup.get("snapshots", [])
    if not isinstance(required, list) or not required or not isinstance(snapshots, list):
        raise RuntimeError("local_backup_snapshot_not_declared")
    local_repo = str(required[0])
    matches = [row for row in snapshots if isinstance(row, dict)
               and row.get("repository") == local_repo and row.get("status") == "ok"]
    if len(matches) != 1 or not matches[0].get("snapshot_id"):
        raise RuntimeError("local_backup_snapshot_ambiguous")
    return str(matches[0]["snapshot_id"])


def map_synthetic_original_path(original_path: str) -> str:
    prefix = "/usr/src/app/upload/"
    if not original_path.startswith(prefix):
        raise RuntimeError("synthetic_original_path_prefix_invalid")
    relative = original_path[len(prefix):]
    components = relative.split("/")
    if not relative or any(part in ("", ".", "..") for part in components):
        raise RuntimeError("synthetic_original_path_unsafe")
    return "/var/lib/immich/data/" + relative


REMOTE_SYNTHETIC_ABSENCE = r'''set -eu
asset_id=$1
original_file=$2
case "$asset_id" in
  ????????-????-????-????-????????????) ;;
  *) exit 20 ;;
esac
sql="SELECT count(*) FROM asset WHERE id = '$asset_id';"
active=$(docker exec immich_postgres psql -U immich -d immich -Atq -v ON_ERROR_STOP=1 -c "$sql")
case "$active" in 0) ;; *) printf 'active=unknown\n'; exit 0 ;; esac
if test -e "$original_file" || test -L "$original_file"; then
  printf 'active=0\nfile=present\n'
else
  printf 'active=0\nfile=absent\n'
fi
'''


def synthetic_absence_proven(asset_id: str, original_path: str, timeout: int = 30) -> bool:
    try:
        uuid.UUID(asset_id)
        host_path = map_synthetic_original_path(original_path)
    except (ValueError, RuntimeError):
        return False
    remote_command = "bash -s -- " + shlex.quote(asset_id) + " " + shlex.quote(host_path)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = subprocess.run(
                ["ssh", "-F", "/dev/null", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", SSH_HOST, remote_command],
                input=REMOTE_SYNTHETIC_ABSENCE,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=9,
                check=False,
            )
            state = parse_remote(result.stdout)
            if result.returncode == 0 and state.get("active") == "0" and state.get("file") == "absent":
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass
        time.sleep(min(5, max(0, deadline - time.monotonic())))
    return False


REMOTE_HOLD_WORKER_BACKUP_LOCK = r'''set -eu
umask 077
exec 9>>/home/egk/.local/state/immich-backup/lock
if ! flock -n 9; then
  printf 'BUSY\n'
  exit 75
fi
printf 'LOCKED\n'
cat >/dev/null
'''


@contextmanager
def synthetic_cleanup_locks():
    """Prevent either media worker from inventorying source while our PNG is removed."""
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    local_lock_path = BACKUP_STATE_DIR / "lock"
    local_lock = local_lock_path.open("a", encoding="utf-8")
    os.chmod(local_lock_path, 0o600)
    remote: subprocess.Popen[str] | None = None
    try:
        try:
            fcntl.flock(local_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("desktop_backup_lock_busy") from None
        if WORKER_BACKUP_HOST not in ("local", "localhost"):
            remote = subprocess.Popen(
                ["ssh", "-F", "/dev/null", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                 WORKER_BACKUP_HOST, "bash", "-s"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
            assert remote.stdin is not None and remote.stdout is not None
            remote.stdin.write(REMOTE_HOLD_WORKER_BACKUP_LOCK)
            remote.stdin.flush()
            selector = selectors.DefaultSelector()
            try:
                selector.register(remote.stdout, selectors.EVENT_READ)
                ready = selector.select(timeout=10)
            finally:
                selector.close()
            response = remote.stdout.readline().strip() if ready else ""
            if response != "LOCKED":
                raise RuntimeError("minitx_backup_lock_busy_or_unavailable")
        yield
    finally:
        try:
            if remote is not None:
                if remote.stdin is not None:
                    try:
                        remote.stdin.close()
                    except OSError:
                        pass
                try:
                    remote.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    remote.terminate()
                    try:
                        remote.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        remote.kill()
                        remote.wait(timeout=3)
        finally:
            fcntl.flock(local_lock, fcntl.LOCK_UN)
            local_lock.close()


def cleanup_synthetic_restore(
    restore: dict[str, object], expected_snapshot: str, asset_id: str, checksum: str,
) -> None:
    if restore.get("snapshot_id") != expected_snapshot or restore.get("worker") != "workstation":
        raise RuntimeError("synthetic_restore_cleanup_proof_mismatch")
    restore_path = Path(str(restore.get("restore_path", "")))
    _, integrity = find_inventory_rows(restore_path, asset_id)
    if integrity.get("checksum", "").lower() != checksum or integrity.get("status") != "verified":
        raise RuntimeError("synthetic_restore_cleanup_checksum_unconfirmed")
    try:
        info = restore_path.lstat()
    except OSError:
        raise RuntimeError("synthetic_restore_cleanup_path_missing") from None
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or restore_path.name.startswith("immich-restore-") is False
        or restore_path.parent.resolve() != Path("/home/egk").resolve()
        or restore_path.resolve() != restore_path
    ):
        raise RuntimeError("synthetic_restore_cleanup_path_unsafe")
    shutil.rmtree(restore_path)
    restore["restored_files_preserved"] = False
    restore["files_cleanup_completed_at"] = time.time()
    atomic_json(MEDIA_RESTORE_STATE, restore)


def check_synthetic_in_backup(asset_id: str, checksum: str, created_at: float) -> tuple[dict[str, object], str]:
    backup = read_object(MEDIA_BACKUP_STATE)
    if not backup or backup.get("kind") != "media" or float(backup.get("created_at", 0)) < created_at:
        raise RuntimeError("fresh_media_backup_not_confirmed")
    report = read_object(MEDIA_BACKUP_REPORT_STATE)
    repo_rows = report.get("repository_status", []) if report else []
    required = backup.get("required_repositories", [])
    repo_map = {
        str(item.get("repository")): item
        for item in repo_rows
        if isinstance(item, dict) and item.get("repository")
    } if isinstance(repo_rows, list) else {}
    if (not isinstance(required, list) or not required or not report
            or report.get("kind") != "media"
            or report.get("worker") != backup.get("worker")
            or report.get("worker_host") != backup.get("worker_host")
            or report.get("required_repositories") != required
            or report.get("mandatory_repositories_healthy") is not True):
        raise RuntimeError("mandatory_backup_repositories_not_confirmed")
    if not all(repo_map.get(str(name), {}).get("status") == "ok" for name in required):
        raise RuntimeError("mandatory_backup_repository_failed")
    if any(float(repo_map[str(name)].get("completed_at", 0) or 0) < created_at for name in required):
        raise RuntimeError("backup_repository_snapshot_precedes_synthetic_upload")
    assets, integrity = find_inventory_rows(MEDIA_BACKUP_STAGE, asset_id)
    if assets.get("checksum", "").lower() != checksum or integrity.get("checksum", "").lower() != checksum:
        raise RuntimeError("synthetic_backup_checksum_mismatch")
    if integrity.get("status") != "verified":
        raise RuntimeError("synthetic_original_not_sha1_verified_in_backup")
    original_path = map_synthetic_original_path(assets.get("originalPath", ""))
    snapshot_id = local_snapshot_id(backup)
    ceph_repository = "s3:http://127.0.0.1:17480/immich-backups"
    ceph_row = repo_map.get(ceph_repository, {})
    ceph_snapshot = None
    if ceph_row.get("status") == "ok" and float(ceph_row.get("completed_at", 0) or 0) >= created_at:
        ceph_matches = [row for row in backup.get("snapshots", [])
                        if isinstance(row, dict) and row.get("repository") == ceph_repository
                        and row.get("status") == "ok" and row.get("snapshot_id") == ceph_row.get("snapshot_id")]
        if len(ceph_matches) == 1:
            ceph_snapshot = str(ceph_row["snapshot_id"])
    backup["_synthetic_original_path"] = assets["originalPath"]
    backup["_synthetic_local_snapshot_id"] = snapshot_id
    backup["_synthetic_ceph_snapshot_id"] = ceph_snapshot
    backup["_synthetic_ceph_degraded"] = ceph_snapshot is None
    missing = int(backup.get("missing", -1))
    baseline_missing = update_missing_baseline(backup, dt.datetime.now(dt.timezone.utc))
    if missing < 0 or baseline_missing < 0 or missing > baseline_missing or int(backup.get("integrity_errors", -1)) != 0:
        raise RuntimeError("media_backup_integrity_baseline_exceeded")
    source_missing = int(backup.get("source_missing", -1))
    source_errors = int(backup.get("source_integrity_errors", -1))
    source_baseline = update_source_missing_baseline(backup, dt.datetime.now(dt.timezone.utc))
    if source_missing < 0 or source_baseline < 0 or source_missing > source_baseline or source_errors != 0:
        raise RuntimeError("primary_source_integrity_baseline_exceeded")
    return backup, original_path


def check_synthetic_in_restore(
    asset_id: str, checksum: str, created_at: float, expected_snapshot: str,
    expected_assets: int, expected_verified: int, expected_missing: int,
    expected_worker_host: str, expected_repository: str,
    expected_required_repositories: list[object],
) -> dict[str, object]:
    restore = read_object(MEDIA_RESTORE_STATE)
    if not restore or restore.get("kind") != "media" or float(restore.get("tested_at", 0)) < created_at:
        raise RuntimeError("fresh_media_restore_not_confirmed")
    if restore.get("snapshot_id") != expected_snapshot:
        raise RuntimeError("restore_snapshot_not_in_fresh_backup")
    if (restore.get("worker") != "workstation"
            or restore.get("worker_host") != expected_worker_host
            or restore.get("repository") != expected_repository
            or restore.get("required_repositories") != expected_required_repositories):
        raise RuntimeError("restore_worker_or_repository_mismatch")
    if int(restore.get("asset_count", -1)) != expected_assets:
        raise RuntimeError("restore_asset_count_mismatch")
    if int(restore.get("originals_verified", -1)) != expected_verified:
        raise RuntimeError("restore_sha1_verified_count_mismatch")
    if int(restore.get("known_missing", -1)) != expected_missing:
        raise RuntimeError("restore_known_missing_count_mismatch")
    restored, integrity = find_inventory_rows(Path(str(restore.get("restore_path", ""))), asset_id)
    if restored.get("checksum", "").lower() != checksum or integrity.get("checksum", "").lower() != checksum:
        raise RuntimeError("synthetic_restore_checksum_mismatch")
    if integrity.get("status") != "verified":
        raise RuntimeError("synthetic_original_not_sha1_verified_in_restore")
    return restore


def run_synthetic(remote: dict[str, str]) -> dict[str, object]:
    if MEDIA_READY_FILE.read_text(encoding="utf-8").strip() != "ready":
        raise RuntimeError("media_ready_gate_not_set")
    if remote.get("media_source_ready") != "yes":
        raise RuntimeError("remote_primary_media_source_not_ready")
    if remote.get("service_immich") != "active" or remote.get("container_immich_server") != "running":
        raise RuntimeError("immich_service_not_ready")
    key = read_api_key()
    server_major = synthetic_server_major()
    verify_synthetic_key_scopes(key)
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = STATE_DIR / "synthetic.lock"
    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("synthetic_run_already_active") from None

        with monitor_lock():
            old_state = read_object(STATE_FILE) or {}
        pending = old_state.get("synthetic")
        if isinstance(pending, dict) and pending.get("phase") not in (None, "complete", "duplicate"):
            synthetic = dict(pending)
            phase = str(synthetic.get("phase"))
            asset_id = str(synthetic.get("asset_id", ""))
            checksum = str(synthetic.get("sha1", ""))
            started = float(synthetic.get("started_at", 0))
            if phase == "upload_inflight" or not asset_id or len(checksum) != 40:
                raise RuntimeError("prior_synthetic_requires_manual_review")
            if phase not in {
                "created", "live_verified", "backup_pending", "backup_verified",
                "restore_pending", "restore_verified", "cleanup_pending",
            }:
                raise RuntimeError("prior_synthetic_requires_manual_review")
        else:
            asset_uuid = str(uuid.uuid4())
            payload = make_synthetic_png(asset_uuid)
            checksum = hashlib.sha1(payload).hexdigest()
            started = dt.datetime.now(dt.timezone.utc).timestamp()
            synthetic = {
                "phase": "upload_inflight",
                "started_at": started,
                "device_asset_id": "immich-monitor-" + asset_uuid,
                "sha1": checksum,
            }
            save_state_synthetic(synthetic)
            http_status, response = upload_multipart(key, asset_uuid, payload, checksum,
                                                   server_major=server_major)
            if response.get("status") != "created" or http_status != 201:
                synthetic.update({"phase": "duplicate", "result": "upload_not_created"})
                synthetic.pop("sha1", None)
                save_state_synthetic(synthetic)
                raise RuntimeError("upload_not_created_no_cleanup_attempted")
            asset_id = str(response.get("id", ""))
            try:
                uuid.UUID(asset_id)
            except (ValueError, AttributeError):
                synthetic.update({"phase": "manual_review", "result": "invalid_created_asset_id"})
                save_state_synthetic(synthetic)
                raise RuntimeError("created_asset_id_invalid_no_cleanup_attempted") from None
            synthetic.update({"phase": "created", "asset_id": asset_id})
            save_state_synthetic(synthetic)

        phase = str(synthetic.get("phase"))
        if phase == "created":
            http_status, original = api_request(f"assets/{asset_id}/original", key=key)
            if http_status != 200 or hashlib.sha1(original).hexdigest() != checksum:
                synthetic.update({"phase": "live_readback_failed"})
                save_state_synthetic(synthetic)
                raise RuntimeError("live_original_sha1_mismatch_no_cleanup_attempted")
            synthetic.update({"phase": "live_verified", "live_sha1_verified": True})
            save_state_synthetic(synthetic)
            phase = "live_verified"

        if phase in ("live_verified", "backup_pending"):
            synthetic.update({"phase": "backup_pending"})
            save_state_synthetic(synthetic)
            try:
                subprocess.run(
                    [sys.executable, str(BACKUP_SCRIPT), "--media"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=3 * 60 * 60, check=True,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as error:
                synthetic["last_error"] = f"backup_{type(error).__name__}"
                save_state_synthetic(synthetic)
                raise RuntimeError("media_backup_not_confirmed_asset_retained") from None
            backup, original_path = check_synthetic_in_backup(asset_id, checksum, started)
            snapshot_id = local_snapshot_id(backup)
            synthetic.update({
                "phase": "backup_verified",
                "backup_created_at": backup.get("created_at"),
                "backup_assets": backup.get("assets"),
                "backup_verified": backup.get("verified"),
                "backup_missing": backup.get("missing"),
                "local_snapshot_id": snapshot_id,
                "ceph_snapshot_id": backup.get("_synthetic_ceph_snapshot_id"),
                "ceph_backup_degraded": backup.get("_synthetic_ceph_degraded"),
                "original_path": backup.get("_synthetic_original_path"),
                "backup_worker_host": backup.get("worker_host"),
                "backup_local_repository": backup.get("required_repositories", [""])[0],
                "backup_required_repositories": backup.get("required_repositories", []),
            })
            save_state_synthetic(synthetic)
            phase = "backup_verified"
        else:
            backup = read_object(MEDIA_BACKUP_STATE)
            snapshot_id = str(synthetic.get("local_snapshot_id", ""))

        if phase in ("backup_verified", "restore_pending"):
            if not snapshot_id:
                raise RuntimeError("synthetic_local_snapshot_id_missing")
            synthetic.update({"phase": "restore_pending"})
            save_state_synthetic(synthetic)
            try:
                subprocess.run(
                    [sys.executable, str(RESTORE_SCRIPT), "--kind", "media", "--snapshot", snapshot_id],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=3 * 60 * 60, check=True,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as error:
                synthetic["last_error"] = f"restore_{type(error).__name__}"
                save_state_synthetic(synthetic)
                raise RuntimeError("media_restore_not_confirmed_asset_retained") from None
            restore = check_synthetic_in_restore(
                asset_id, checksum, started, snapshot_id,
                int(synthetic.get("backup_assets", -1)),
                int(synthetic.get("backup_verified", -1)),
                int(synthetic.get("backup_missing", -1)),
                str(synthetic.get("backup_worker_host", "")),
                str(synthetic.get("backup_local_repository", "")),
                synthetic.get("backup_required_repositories", []),
            )
            synthetic.update({
                "phase": "restore_verified",
                "restore_tested_at": restore.get("tested_at"),
                "restore_path": restore.get("restore_path"),
                "restore_snapshot_id": restore.get("snapshot_id"),
                "restore_verified_asset_id": asset_id,
                "restore_verified_sha1": checksum,
                "restore_files_cleaned": False,
            })
            save_state_synthetic(synthetic)
            phase = "restore_verified"

        if phase in ("restore_verified", "cleanup_pending"):
            synthetic.update({"phase": "cleanup_pending"})
            save_state_synthetic(synthetic)
            snapshot_id = str(synthetic.get("local_snapshot_id", ""))
            original_path = str(synthetic.get("original_path", ""))
            if (synthetic.get("restore_verified_asset_id") != asset_id
                    or synthetic.get("restore_verified_sha1") != checksum
                    or synthetic.get("restore_snapshot_id") != snapshot_id
                    or not original_path):
                raise RuntimeError("synthetic_cleanup_ownership_proof_missing")
            if synthetic.get("restore_files_cleaned") is not True:
                restore = read_object(MEDIA_RESTORE_STATE)
                restore_path = Path(str(synthetic.get("restore_path", "")))
                try:
                    restore_path.lstat()
                    restore_path_exists = True
                except OSError:
                    restore_path_exists = False
                if restore_path_exists:
                    if not restore:
                        raise RuntimeError("synthetic_restore_report_missing_before_cleanup")
                    checked_restore = check_synthetic_in_restore(
                        asset_id, checksum, started, snapshot_id,
                        int(synthetic.get("backup_assets", -1)),
                        int(synthetic.get("backup_verified", -1)),
                        int(synthetic.get("backup_missing", -1)),
                        str(synthetic.get("backup_worker_host", "")),
                        str(synthetic.get("backup_local_repository", "")),
                        synthetic.get("backup_required_repositories", []),
                    )
                    if checked_restore.get("restore_path") != synthetic.get("restore_path"):
                        raise RuntimeError("synthetic_restore_cleanup_path_changed")
                    cleanup_synthetic_restore(restore, snapshot_id, asset_id, checksum)
                elif not (restore and restore.get("restored_files_preserved") is False
                          and restore.get("snapshot_id") == snapshot_id
                          and restore.get("restore_path") == str(restore_path)):
                    raise RuntimeError("synthetic_restore_cleanup_not_proven")
                synthetic["restore_files_cleaned"] = True
                save_state_synthetic(synthetic)
            body = json.dumps({"ids": [asset_id], "force": True}).encode("utf-8")
            with synthetic_cleanup_locks():
                try:
                    status, _ = api_request(
                        "assets", key=key, method="DELETE", body=body,
                        content_type="application/json",
                    )
                except RuntimeError as error:
                    if str(error) == "api_http_404":
                        status = 404
                    else:
                        synthetic["last_error"] = "cleanup_request_failed"
                        save_state_synthetic(synthetic)
                        raise error
                if status not in (200, 204, 404):
                    synthetic["last_error"] = "cleanup_status_unexpected"
                    save_state_synthetic(synthetic)
                    raise RuntimeError("synthetic_cleanup_not_confirmed")
                if not synthetic_absence_proven(asset_id, original_path, timeout=30):
                    synthetic["last_error"] = "cleanup_pending_database_or_file"
                    save_state_synthetic(synthetic)
                    raise RuntimeError("synthetic_cleanup_pending_database_or_file")
            synthetic.update({"phase": "complete", "completed_at": dt.datetime.now(dt.timezone.utc).timestamp()})
            synthetic.pop("last_error", None)
            save_state_synthetic(synthetic)
        return {
            "phase": synthetic.get("phase"),
            "live_sha1_verified": synthetic.get("live_sha1_verified", False),
            "ceph_backup_degraded": synthetic.get("ceph_backup_degraded", True),
        }


def run_unlocked() -> int:
    now = dt.datetime.now(dt.timezone.utc)
    result: dict[str, object] = {
        "checked_at_utc": now.isoformat(timespec="seconds"),
        "url": BASE_URL,
        "checks": {},
        "observations": {},
        "errors": [],
    }
    checks: dict[str, bool] = result["checks"]  # type: ignore[assignment]
    observations: dict[str, object] = result["observations"]  # type: ignore[assignment]
    errors: list[str] = result["errors"]  # type: ignore[assignment]

    try:
        status, version = get_json("server/version")
        observations["api_version"] = version
        checks["api_version_endpoint"] = status == 200 and isinstance(version, dict)
    except Exception as error:  # Never include request URLs, headers, or response bodies.
        checks["api_version_endpoint"] = False
        errors.append(f"api_version_endpoint:{type(error).__name__}")

    try:
        status, ping = get_json("server/ping")
        observations["api_ping"] = ping.get("res") if isinstance(ping, dict) else "unexpected"
        checks["api_ping"] = status == 200 and isinstance(ping, dict) and ping.get("res") == "pong"
    except Exception as error:
        checks["api_ping"] = False
        errors.append(f"api_ping:{type(error).__name__}")

    try:
        completed = subprocess.run(
            ["ssh", "-F", "/dev/null", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", SSH_HOST, "bash", "-s"],
            input=REMOTE_READONLY,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=SSH_TIMEOUT,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError("remote_readonly_probe_failed")
        remote = parse_remote(completed.stdout)
        observations["remote"] = remote
        checks["remote_probe"] = True
        checks["service_immich"] = remote.get("service_immich") == "active"
        for container in ("immich_server", "immich_postgres", "immich_redis"):
            checks[f"container_{container}"] = remote.get(f"container_{container}") == "running"
        checks["primary_media_source_ext4"] = remote.get("media_source_ready") == "yes"
        source_free = int(remote.get("source_free_bytes") or "0")
        workstation_free = shutil.disk_usage("/home/egk").free
        checks["primary_source_free_space"] = source_free >= MIN_FREE_BYTES
        checks["backup_worker_free_space"] = workstation_free >= MIN_FREE_BYTES
        observations["primary_source_free_bytes"] = source_free
        observations["backup_worker_free_bytes"] = workstation_free
        observations["backup_worker_host"] = socket.gethostname().split(".", 1)[0]
        observations["minimum_free_bytes"] = MIN_FREE_BYTES
        checks["database_aggregate"] = remote.get("assets_24h", "unknown") != "unknown"
        observations["assets_24h"] = remote.get("assets_24h")
        observations["assets_7d"] = remote.get("assets_7d")
        last_asset_epoch = int(remote.get("last_asset_epoch") or "0")
        observations["last_asset_created_utc"] = (
            dt.datetime.fromtimestamp(last_asset_epoch, dt.timezone.utc).isoformat(timespec="seconds")
            if last_asset_epoch
            else None
        )
        observations["machine_learning"] = remote.get("machine_learning", "unknown")
    except Exception as error:
        checks["remote_probe"] = False
        errors.append(f"remote_probe:{type(error).__name__}")

    observations["ceph_health"] = read_ceph_health()

    local_checks, local_observations = local_media_evidence(now)
    checks.update(local_checks)
    observations.update(local_observations)
    try:
        ready_gate = MEDIA_READY_FILE.is_file() and MEDIA_READY_FILE.read_text(encoding="utf-8").strip() == "ready"
    except OSError:
        ready_gate = False
    observations["synthetic_ready_gate"] = ready_gate and API_KEY_FILE.is_file()

    result["status"] = "PASS" if checks and all(checks.values()) else "FAIL"
    previous_status = None
    previous = read_object(STATE_FILE)
    try:
        previous_status = previous.get("status") if previous else None
    except (OSError, ValueError, AttributeError):
        pass
    if previous and isinstance(previous.get("synthetic"), dict):
        result["synthetic"] = previous["synthetic"]
    ceph_health = str(observations.get("ceph_health", "unknown"))
    ceph_degraded = bool(observations.get("cluster_copy_degraded", False))
    prior_ceph = previous.get("ceph_signal") if previous else None
    ceph_signal = {"health": ceph_health, "copy_degraded": ceph_degraded}
    worker_signal = {
        "selected": observations.get("media_backup_worker"),
        "degraded": observations.get("media_backup_worker_degraded", {}),
        "minitx_report_available": observations.get("minitx_worker_report_available", False),
    }
    prior_worker = previous.get("worker_signal") if previous else None
    result["ceph_signal"] = ceph_signal
    result["worker_signal"] = worker_signal
    atomic_json(STATE_FILE, result)
    event_record = dict(result)
    if isinstance(event_record.get("synthetic"), dict):
        event_record["synthetic"] = {"phase": event_record["synthetic"].get("phase")}
    with EVENTS_FILE.open("a", encoding="utf-8") as events:
        events.write(json.dumps(event_record, ensure_ascii=False, sort_keys=True) + "\n")
        events.flush()
        os.fsync(events.fileno())
    os.chmod(EVENTS_FILE, 0o600)

    status = str(result["status"])
    failed = [name for name, passed in checks.items() if not passed]
    summary = f"status={status} failed={','.join(failed) if failed else 'none'}"
    if status != previous_status:
        priority = "user.err" if status == "FAIL" else "user.notice"
        subprocess.run(["logger", "-t", "immich-reliability-monitor", "-p", priority, summary], check=False)
    if ceph_health not in ("unknown", "not-installed") or ceph_degraded:
        if prior_ceph != ceph_signal:
            ceph_priority = "user.warning" if ceph_health.startswith("HEALTH_") and ceph_health != "HEALTH_OK" or ceph_degraded else "user.notice"
            subprocess.run([
                "logger", "-t", "immich-reliability-monitor", "-p", ceph_priority,
                f"Ceph informational state health={ceph_health} backup_copy_degraded={str(ceph_degraded).lower()}",
            ], check=False)
    if prior_worker != worker_signal and (
        any(bool(value) for value in worker_signal["degraded"].values())
        or not worker_signal["minitx_report_available"]
    ):
        subprocess.run([
            "logger", "-t", "immich-reliability-monitor", "-p", "user.warning",
            f"Backup worker state selected={worker_signal['selected']} degraded={json.dumps(worker_signal['degraded'], sort_keys=True)} minitx_report_available={str(worker_signal['minitx_report_available']).lower()}",
        ], check=False)
    display = dict(result)
    synthetic = display.get("synthetic")
    if isinstance(synthetic, dict):
        display["synthetic"] = {"phase": synthetic.get("phase")}
    print(json.dumps(display, ensure_ascii=False, sort_keys=True))
    return 0 if status == "PASS" else 1


def run() -> int:
    with monitor_lock():
        return run_unlocked()


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Immich reliability checks")
    parser.add_argument(
        "--synthetic", action="store_true",
        help="run the gated upload, live SHA-1, media-backup, restore, and cleanup check",
    )
    args = parser.parse_args()
    run()
    if not args.synthetic:
        return 0 if (read_object(STATE_FILE) or {}).get("status") == "PASS" else 1
    try:
        with monitor_lock():
            state = read_object(STATE_FILE) or {}
            remote = state.get("observations", {}).get("remote", {})
        synthetic_result = run_synthetic(remote if isinstance(remote, dict) else {})
    except Exception as error:
        old = read_object(STATE_FILE) or {}
        synthetic = old.get("synthetic")
        if isinstance(synthetic, dict) and synthetic.get("phase") not in ("complete", "duplicate"):
            synthetic["last_error"] = str(error)
            save_state_synthetic(synthetic)
        summary = f"synthetic=FAIL reason={str(error)}"
        subprocess.run(["logger", "-t", "immich-reliability-monitor", "-p", "user.err", summary], check=False)
        print(json.dumps({"synthetic_status": "FAIL", "reason": str(error)}, sort_keys=True))
        return 1
    print(json.dumps({"synthetic_status": "PASS", **synthetic_result}, sort_keys=True))
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
