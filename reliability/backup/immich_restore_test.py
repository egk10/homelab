#!/usr/bin/env python3
"""Restore immutable snapshot into private directory and isolated PostgreSQL."""
import argparse
from contextlib import nullcontext
import csv
import fcntl
import hashlib
import json
import os
import platform
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import time
from immich_backup import HOME, STATE, REPOSITORIES, MANDATORY_REPOSITORIES, WORKER, SECONDARY_OPTIONS, SECONDARY_HOST, CEPH_REPOSITORY, ceph_tunnel, restic, atomic_json, run

def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--kind', choices=['metadata-only', 'media'], default='media')
    selector = parser.add_mutually_exclusive_group()
    selector.add_argument('--secondary', action='store_true')
    selector.add_argument('--ceph', action='store_true')
    parser.add_argument('--snapshot')
    parser.add_argument('--cleanup', action='store_true', help='Remove only this test restore after recording success')
    args = parser.parse_args()
    lock = (STATE / 'lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX)
    repo = CEPH_REPOSITORY if args.ceph else REPOSITORIES[int(args.secondary)]
    backup = json.loads((STATE / ('last-' + args.kind + '.json')).read_text())
    snapshot = args.snapshot or next(snapshot['snapshot_id'] for snapshot in backup['snapshots'] if snapshot['repository'] == repo)
    destination = Path(tempfile.mkdtemp(prefix='immich-restore-', dir=HOME))
    with ceph_tunnel() if args.ceph else nullcontext():
        restic(repo, 'check', capture_output=True, text=True)
        restic(repo, 'restore', snapshot, '--target', str(destination), capture_output=True, text=True)
    manifests = list(destination.rglob('manifest.json'))
    if len(manifests) != 1:
        raise RuntimeError('Expected exactly one backed-up manifest')
    manifest = json.loads(manifests[0].read_text())
    stage = manifests[0].parent
    dump = stage / 'database.dump'
    if hashlib.sha256(dump.read_bytes()).hexdigest() != manifest['database_sha256']:
        raise RuntimeError('Restored database dump hash mismatch')
    image = manifest['database_image']
    if subprocess.run(['docker', 'image', 'inspect', image], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        run(['docker', 'pull', image], stdout=subprocess.DEVNULL)
    name = 'immich-restore-test-' + secrets.token_hex(5)
    started = False
    try:
        # No ports, no network and only a tmpfs database: production cannot be touched.
        run(['docker', 'run', '-d', '--name', name, '--network', 'none', '--tmpfs', '/var/lib/postgresql/data:rw,size=1g', '--memory', '2g', '--cpus', '2', '-e', 'POSTGRES_HOST_AUTH_METHOD=trust', '-e', 'POSTGRES_USER=immich', '-e', 'POSTGRES_DB=immich', image], stdout=subprocess.DEVNULL)
        started = True
        for _ in range(60):
            ready = subprocess.run(['docker', 'exec', name, 'pg_isready', '-U', 'immich', '-d', 'immich'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Isolated restore PostgreSQL did not become ready')
        with dump.open('rb') as source:
            run(['docker', 'exec', '-i', name, 'pg_restore', '--username=immich', '--dbname=immich', '--no-owner', '--no-privileges', '--exit-on-error', '--single-transaction'], stdin=source, stdout=subprocess.DEVNULL)
        counts = run(['docker', 'exec', name, 'psql', '-U', 'immich', '-d', 'immich', '-Atc', 'SELECT count(*) FROM asset'], capture_output=True, text=True)
        expected = len(list(csv.DictReader((stage / 'assets.csv').open())))
        if int(counts.stdout.strip()) != expected:
            raise RuntimeError('Restored asset count differs from inventory')
        verified = 0
        missing = None
        if args.kind == 'media':
            missing = 0
            results = json.loads((stage / 'asset-integrity.json').read_text())
            for row in results:
                if row['status'] != 'verified':
                    missing += 1
                    continue
                relative = row['originalPath']
                for prefix in ('/usr/src/app/upload/', '/data/'):
                    if relative.startswith(prefix):
                        relative = relative[len(prefix):]
                        break
                digest = hashlib.sha1()
                with (stage / 'data' / relative).open('rb') as handle:
                    for block in iter(lambda: handle.read(1024 * 1024), b''):
                        digest.update(block)
                if digest.hexdigest() != row['checksum']:
                    raise RuntimeError('Restored original asset hash mismatch')
                verified += 1
        report = {'tested_at': time.time(), 'worker': WORKER, 'worker_host': platform.node(), 'required_repositories': MANDATORY_REPOSITORIES, 'repository': repo, 'snapshot_id': snapshot, 'kind': args.kind, 'database_restored': True, 'asset_count': expected, 'originals_verified': verified, 'known_missing': missing, 'restore_path': str(destination), 'database_image': image, 'restored_files_preserved': not args.cleanup, 'library_complete': manifest.get('library_complete', False)}
        suffix = '-ceph' if args.ceph else '-secondary' if args.secondary else ''
        atomic_json(STATE / ('last-restore-' + args.kind + suffix + '.json'), report)
        if WORKER == 'minitx' and args.kind == 'media':
            target = 'minitx-last-restore-media' + suffix + '.json'
            command = f'umask 077; mkdir -p /home/egk/.local/state/immich-backup; cat > /home/egk/.local/state/immich-backup/{target}.tmp && mv /home/egk/.local/state/immich-backup/{target}.tmp /home/egk/.local/state/immich-backup/{target}'
            try:
                run(['ssh', *SECONDARY_OPTIONS, SECONDARY_HOST, command], input=json.dumps(report), text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as error:
                report['desktop_report_mirror_error'] = type(error).__name__
                atomic_json(STATE / ('last-restore-' + args.kind + suffix + '.json'), report)
        print(json.dumps(report, indent=2))
    finally:
        if started:
            run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL)
    if args.cleanup:
        if destination.parent != HOME or not destination.name.startswith('immich-restore-'):
            raise RuntimeError('Refusing unsafe restore cleanup path')
        shutil.rmtree(destination)
    # Keep restored evidence; operator removes only this reported unique directory.

if __name__ == '__main__':
    main()
