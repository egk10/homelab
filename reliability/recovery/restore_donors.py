#!/usr/bin/env python3
"""Restore exact-checksum donor files to existing Immich paths, not DB rows."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import time


def sha1(path):
    digest = hashlib.sha1()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    os.umask(0o077)
    source = Path('/var/backups/immich-preservation/phone-donors')
    target_root = Path('/var/lib/immich/data')
    query = '''select coalesce(json_agg(t),'[]'::json) from (
        select id, "originalPath" as path, encode(checksum,'hex') as checksum from asset order by id) t;'''
    rows = json.loads(subprocess.check_output(['docker', 'exec', 'immich_postgres', 'psql', '-U', 'immich', '-d', 'immich', '-Atc', query], text=True))
    donors = {}
    for path in source.iterdir():
        if path.is_file() and len(path.stem) == 40:
            if sha1(path) != path.stem:
                raise RuntimeError('Donor hash mismatch; refusing restore')
            donors[path.stem] = path
    restored = verified = 0
    results = []
    for row in rows:
        prefix = '/usr/src/app/upload/'
        if not row['path'].startswith(prefix):
            raise RuntimeError('Unexpected original path')
        relative = PurePosixPath(row['path'][len(prefix):])
        if relative.is_absolute() or '..' in relative.parts:
            raise RuntimeError('Unsafe original path')
        target = target_root / relative
        status = 'missing'
        if target.is_file() and sha1(target) == row['checksum']:
            status = 'verified'
            verified += 1
        elif row['checksum'] in donors:
            if target.exists():
                quarantine = Path('/var/backups/immich-preservation/quarantine') / relative
                quarantine.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, quarantine)
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(target.name + '.donor-part')
            shutil.copyfile(donors[row['checksum']], temp)
            with temp.open('rb') as handle:
                os.fsync(handle.fileno())
            if sha1(temp) != row['checksum']:
                raise RuntimeError('Restored original checksum mismatch')
            temp.chmod(0o644)
            temp.replace(target)
            restored += 1
            status = 'restored'
        results.append({**row, 'status': status})
    report = {'created_at': time.time(), 'restored': restored, 'already_verified': verified,
              'missing': sum(r['status'] == 'missing' for r in results), 'results': results}
    output = Path('/home/egk/homelab/reliability/recovery/phone-restoration.json')
    output.write_text(json.dumps(report, indent=2))
    output.chmod(0o600)
    print(json.dumps({k: v for k, v in report.items() if k != 'results'}))


if __name__ == '__main__':
    main()
