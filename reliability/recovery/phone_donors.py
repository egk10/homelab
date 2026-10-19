#!/usr/bin/env python3
"""Read connected MTP media, stage only exact hashes known to Immich.

Never write or delete anything on the phone, never change database rows.
"""
import collections
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


def main():
    os.umask(0o077)
    root = Path('/home/egk/immich-phone-recovery')
    root.mkdir(exist_ok=True, mode=0o700)
    query = '''select coalesce(json_agg(t),'[]'::json) from (
        select id, "originalPath" as path, "originalFileName" as name,
        encode(checksum,'hex') as checksum from asset order by id) t;'''
    script = 'import subprocess\nprint(subprocess.check_output(["docker","exec","immich_postgres","psql","-U","immich","-d","immich","-Atc",' + repr(query) + '],text=True))\n'
    rows = json.loads(subprocess.check_output(['ssh', '-o', 'BatchMode=yes', 'cloudvero', 'python3', '-'], input=script, text=True))
    wanted = collections.defaultdict(list)
    names = set()
    for row in rows:
        wanted[row['checksum']].append(row)
        names.add(row['name'].casefold())
    devices = list(Path('/run/user/1000/gvfs').glob('mtp:*'))
    if len(devices) != 1:
        raise SystemExit('Exactly one unlocked MTP device is required')
    media_roots = []
    for storage in devices[0].iterdir():
        for folder in ('DCIM', 'Pictures', 'Movies', 'Download', 'WhatsApp/Media',
                       'Android/media/com.whatsapp/WhatsApp/Media'):
            candidate = storage / folder
            if candidate.is_dir():
                media_roots.append(candidate)
    started = time.time()
    scanned = candidates = matches = failures = 0
    found = []
    suffixes = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.webp', '.gif', '.mp4', '.mov', '.mkv', '.3gp', '.avi'}
    for media in media_roots:
        for directory, dirs, files in os.walk(media):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('Sent', 'Private')]
            for filename in files:
                scanned += 1
                if filename.casefold() not in names or Path(filename).suffix.lower() not in suffixes:
                    continue
                candidates += 1
                path = Path(directory) / filename
                digest = hashlib.sha1()
                try:
                    with path.open('rb') as handle:
                        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                            digest.update(chunk)
                    value = digest.hexdigest()
                    if value in wanted:
                        target = root / (value + path.suffix.lower())
                        if not target.exists():
                            shutil.copyfile(path, target)
                            target.chmod(0o600)
                        # Verify the staged second read independently of the phone read.
                        confirm = hashlib.sha1()
                        with target.open('rb') as handle:
                            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                                confirm.update(chunk)
                        if confirm.hexdigest() != value:
                            raise RuntimeError('Staged donor hash mismatch')
                        found.append({'sha1': value, 'staged_file': str(target),
                                      'assets': wanted[value], 'phone_file': str(path)})
                        matches += 1
                except (OSError, RuntimeError):
                    failures += 1
                if candidates % 25 == 0:
                    print(json.dumps({'media_entries': scanned, 'hashed_candidates': candidates,
                                      'matching_files': matches, 'read_errors': failures,
                                      'seconds': round(time.time() - started)}), flush=True)
    report = {'created_at': time.time(), 'media_entries': scanned, 'hashed_candidates': candidates,
              'matching_files': matches, 'read_errors': failures, 'found': found}
    output = root / 'donors.json'
    output.write_text(json.dumps(report, indent=2))
    output.chmod(0o600)
    print(json.dumps({k: v for k, v in report.items() if k != 'found'}), flush=True)


if __name__ == '__main__':
    main()
