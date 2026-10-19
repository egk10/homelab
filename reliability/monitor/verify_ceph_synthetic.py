#!/usr/bin/env python3
"""Read back only the gated E2E's synthetic PNG from its immutable Ceph backup."""
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / 'backup'))
from immich_backup import STATE, STAGE, CEPH_REPOSITORY, atomic_json, ceph_tunnel, restic


def main():
    os.umask(0o077)
    state = json.loads((ROOT / 'state.json').read_text())['synthetic']
    if state.get('phase') != 'complete' or not state.get('live_sha1_verified'):
        raise RuntimeError('Completed synthetic proof is required')
    if not str(state.get('device_asset_id', '')).startswith('immich-monitor-'):
        raise RuntimeError('Synthetic identity is required')
    uuid.UUID(state['asset_id'])
    checksum = state['sha1']
    snapshot = state.get('ceph_snapshot_id', '')
    if not re.fullmatch('[a-f0-9]{40}', checksum) or not re.fullmatch('[a-f0-9]{64}', snapshot):
        raise RuntimeError('Valid checksum and Ceph snapshot are required')
    original = state['original_path']
    prefix = '/usr/src/app/upload/'
    if not original.startswith(prefix):
        raise RuntimeError('Unexpected synthetic original path')
    relative = PurePosixPath(original[len(prefix):])
    if relative.is_absolute() or '..' in relative.parts or relative.suffix.lower() != '.png':
        raise RuntimeError('Unsafe synthetic original path')
    backed_up_path = str(STAGE / 'media/data' / relative)
    with (STATE / 'lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with ceph_tunnel():
            result = restic(CEPH_REPOSITORY, 'dump', snapshot, backed_up_path,
                            capture_output=True, timeout=180)
    if len(result.stdout) > 1024 * 1024 or hashlib.sha1(result.stdout).hexdigest() != checksum:
        raise RuntimeError('Synthetic Ceph readback hash mismatch')
    proof = {'tested_at': time.time(), 'asset_id': state['asset_id'],
             'repository': CEPH_REPOSITORY, 'snapshot_id': snapshot,
             'sha1_verified': True, 'bytes': len(result.stdout),
             'live_cleanup_previously_confirmed': True}
    atomic_json(Path('/home/egk/.local/state/immich-monitor/ceph-synthetic-proof.json'), proof)
    print(json.dumps({key: value for key, value in proof.items() if key != 'asset_id'}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'sha1_verified': False, 'error_type': type(error).__name__}))
        raise SystemExit(1)
