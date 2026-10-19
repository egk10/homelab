#!/usr/bin/env python3
"""Bound media backup history; preserve all pre-migration metadata snapshots."""
import fcntl
import time
from immich_backup import STATE, REPOSITORIES, MANDATORY_REPOSITORIES, CEPH_REPOSITORY, ceph_tunnel, restic, sanitized_failure, atomic_json

if __name__ == '__main__':
    with (STATE / 'lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not (STATE / 'last-media.json').is_file():
            raise RuntimeError('No successful media backup: retention disabled')
        statuses = []
        for repo in REPOSITORIES:
            try:
                restic(repo, 'forget', '--prune', '--host', 'immich-cloudvero', '--tag', 'immich,media', '--group-by', 'host,tags', '--keep-daily', '30', '--keep-weekly', '12', '--keep-monthly', '12')
                statuses.append({'repository': repo, 'status': 'ok'})
            except Exception as error:
                statuses.append(sanitized_failure(repo, error))
        if (STATE / 'ceph-rgw-credentials.json').is_file():
            try:
                with ceph_tunnel():
                    restic(CEPH_REPOSITORY, 'forget', '--prune', '--host', 'immich-cloudvero', '--tag', 'immich,media', '--group-by', 'host,tags', '--keep-daily', '30', '--keep-weekly', '12', '--keep-monthly', '12')
                statuses.append({'repository': CEPH_REPOSITORY, 'status': 'ok'})
            except Exception as error:
                statuses.append(sanitized_failure(CEPH_REPOSITORY, error))
        atomic_json(STATE / 'last-retention.json', {'completed_at': time.time(), 'repository_status': statuses})
        if any(status['status'] != 'ok' and status['repository'] in MANDATORY_REPOSITORIES for status in statuses):
            raise RuntimeError('Required repository retention failed')
