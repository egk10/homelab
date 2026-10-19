#!/usr/bin/env python3
"""Read-only full SHA1 audit of primary originals from a captured CSV inventory."""
import csv
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

results = []
for row in csv.DictReader(sys.stdin):
    original = row['originalPath']
    relative = next((original[len(prefix):] for prefix in ('/usr/src/app/upload/', '/data/') if original.startswith(prefix)), None)
    status = 'unsupported-path'
    if relative and not PurePosixPath(relative).is_absolute() and '..' not in PurePosixPath(relative).parts:
        source = Path('/var/lib/immich/data') / relative
        try:
            digest = hashlib.sha1()
            with source.open('rb') as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b''):
                    digest.update(block)
            status = 'verified' if digest.hexdigest() == row['checksum'] else 'hash-mismatch'
        except FileNotFoundError:
            status = 'missing'
        except OSError:
            status = 'read-error'
    results.append({'id': row['id'], 'originalPath': original, 'checksum': row['checksum'], 'status': status})
print(json.dumps(results))
