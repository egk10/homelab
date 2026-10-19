#!/usr/bin/env python3
"""Monthly rehearsals of both repositories required by this worker role."""
import subprocess
from immich_backup import WORKER

for selector in ([], ['--ceph'] if WORKER == 'minitx' else ['--secondary']):
    subprocess.run(['/usr/bin/python3', '/home/egk/homelab/reliability/backup/immich_restore_test.py', '--cleanup', *selector], check=True)
