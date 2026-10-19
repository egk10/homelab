#!/usr/bin/env python3
"""Search renamed media by exact original byte size and SHA1, read-only phone."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


def main():
    os.umask(0o077)
    report = json.loads(Path('/home/egk/homelab/reliability/recovery/phone-restoration.json').read_text())
    missing = {r['id']: r for r in report['results'] if r['status'] == 'missing'}
    query = '''select coalesce(json_agg(t),'[]'::json) from (
        select "assetId" as id, "fileSizeInByte" as bytes from asset_exif) t;'''
    remote = 'import subprocess\nprint(subprocess.check_output(["docker","exec","immich_postgres","psql","-U","immich","-d","immich","-Atc",' + repr(query) + '],text=True))\n'
    sizes = json.loads(subprocess.check_output(['ssh', '-o', 'BatchMode=yes', 'cloudvero', 'python3', '-'], input=remote, text=True))
    wanted_sizes = {int(r['bytes']) for r in sizes if r['id'] in missing and r['bytes']}
    wanted = {r['checksum']: r for r in missing.values()}
    root = Path('/home/egk/immich-phone-recovery')
    devices = list(Path('/run/user/1000/gvfs').glob('mtp:*'))
    if len(devices) != 1:
        raise SystemExit('Exactly one unlocked MTP device required')
    extensions = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.webp', '.gif', '.mp4', '.mov', '.mkv', '.3gp', '.avi'}
    scanned = hashed = errors = 0
    found = []
    started = time.time()
    for storage in devices[0].iterdir():
        for name in ('DCIM', 'Pictures', 'Movies', 'Download', 'Android/media', 'WhatsApp/Media'):
            media = storage / name
            if not media.is_dir():
                continue
            for directory, dirs, files in os.walk(media):
                dirs[:] = [d for d in dirs if d not in ('.thumbnails', '.Trash')]
                for filename in files:
                    if Path(filename).suffix.lower() not in extensions:
                        continue
                    scanned += 1
                    path = Path(directory) / filename
                    try:
                        if path.stat().st_size not in wanted_sizes:
                            continue
                        hashed += 1
                        digest = hashlib.sha1()
                        with path.open('rb') as handle:
                            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                                digest.update(chunk)
                        value = digest.hexdigest()
                        if value not in wanted:
                            continue
                        target = root / (value + path.suffix.lower())
                        temp = target.with_suffix(target.suffix + '.phone-part')
                        shutil.copyfile(path, temp)
                        digest = hashlib.sha1()
                        with temp.open('rb') as handle:
                            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                                digest.update(chunk)
                        if digest.hexdigest() != value:
                            raise RuntimeError('Donor copy mismatch')
                        temp.replace(target)
                        found.append({'sha1': value, 'staged_file': str(target), 'asset': wanted[value]})
                    except (OSError, RuntimeError):
                        errors += 1
                    if scanned % 100 == 0:
                        print(json.dumps({'media_scanned': scanned, 'size_candidates_hashed': hashed,
                                          'matching_missing': len(found), 'read_errors': errors}), flush=True)
    result = {'created_at': time.time(), 'media_scanned': scanned, 'size_candidates_hashed': hashed,
              'matching_missing': len(found), 'read_errors': errors, 'seconds': round(time.time() - started), 'found': found}
    output = root / 'donors-extra.json'
    output.write_text(json.dumps(result, indent=2)); output.chmod(0o600)
    print(json.dumps({k: v for k, v in result.items() if k != 'found'}), flush=True)


if __name__ == '__main__':
    main()
