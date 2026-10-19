#!/usr/bin/env python3
"""Pull database first, then media; encrypted snapshots in two independent repos."""
import argparse
import csv
from contextlib import contextmanager
import fcntl
import hashlib
import io
import json
import os
import platform
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time

HOME = Path('/home/egk')
STATE = HOME / '.local/state/immich-backup'
STAGE = HOME / 'immich-backup-staging'
PASSWORD = STATE / 'restic-password'
WORKER = os.environ.get('IMMICH_BACKUP_WORKER', 'workstation')
if WORKER not in ('workstation', 'minitx'):
    raise RuntimeError('Unknown backup worker role')
if (WORKER == 'minitx') != (platform.node().split('.')[0] == 'minitx'):
    raise RuntimeError('Backup worker role does not match this machine')
SECONDARY_HOST = '100.64.163.40' if WORKER == 'minitx' else 'minitx'
REPOSITORIES = [str(HOME / 'immich-backup-restic'), f'sftp:egk@{SECONDARY_HOST}:/home/egk/immich-backup-restic']
CEPH_REPOSITORY = 's3:http://127.0.0.1:17480/immich-backups'
MANDATORY_REPOSITORIES = [REPOSITORIES[0], CEPH_REPOSITORY if WORKER == 'minitx' else REPOSITORIES[1]]
RESTIC_BINARY = shutil.which('restic') or str(HOME / '.local/bin/restic')
SSH_OPTIONS = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=3']
SSH = ['ssh', *SSH_OPTIONS, 'cloudvero']
SECONDARY_OPTIONS = SSH_OPTIONS + (['-i', str(HOME / '.ssh/immich-backup-worker'), '-o', 'IdentitiesOnly=yes'] if WORKER == 'minitx' else [])
SQL = '''COPY (SELECT id, "originalPath", encode(checksum,'hex') AS checksum FROM asset ORDER BY id) TO STDOUT WITH CSV HEADER'''

def run(argv, **kw):
    return subprocess.run(argv, check=True, **kw)

def restic(repo, *args, **kw):
    env = dict(os.environ, RESTIC_REPOSITORY=repo, RESTIC_PASSWORD_FILE=str(PASSWORD))
    env.pop('RESTIC_PASSWORD', None)
    options = []
    if repo.startswith('sftp:'):
        sftp_args = '-oBatchMode=yes -oConnectTimeout=15 -oServerAliveInterval=30 -oServerAliveCountMax=3'
        if WORKER == 'minitx':
            sftp_args += ' -i/home/egk/.ssh/immich-backup-worker -oIdentitiesOnly=yes'
        options += ['-o', 'sftp.args=' + sftp_args]
    if repo == CEPH_REPOSITORY:
        env.update(ceph_env())
        options += ['-o', 's3.bucket-lookup=path']
    return run([RESTIC_BINARY, '--retry-lock', '5m', *options, *args], env=env, **kw)

def ceph_env():
    credential = json.loads((STATE / 'ceph-rgw-credentials.json').read_text())
    return {'AWS_ACCESS_KEY_ID': credential['access'], 'AWS_SECRET_ACCESS_KEY': credential['secret'], 'AWS_DEFAULT_REGION': 'us-east-1', 'AWS_EC2_METADATA_DISABLED': 'true', 'AWS_PAGER': '', 'AWS_MAX_ATTEMPTS': '2'}

@contextmanager
def ceph_tunnel():
    tunnel = subprocess.Popen(['ssh', *SSH_OPTIONS, '-o', 'ExitOnForwardFailure=yes', '-N', '-L', '127.0.0.1:17480:127.0.0.1:7480', 'cloudvero'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            if tunnel.poll() is not None:
                raise RuntimeError('Private Ceph SSH tunnel could not start')
            try:
                with socket.create_connection(('127.0.0.1', 17480), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.25)
        else:
            raise RuntimeError('Private Ceph tunnel not ready')
        yield
    finally:
        if tunnel.poll() is None:
            tunnel.terminate()
            tunnel.wait(timeout=15)

def aws(*args, check=True):
    if shutil.which('aws'):
        return subprocess.run(['aws', '--endpoint-url', 'http://127.0.0.1:17480', '--cli-connect-timeout', '10', '--cli-read-timeout', '60', 's3api', *args], env=dict(os.environ, **ceph_env()), check=check, capture_output=True, text=True)
    # Existing Cloudvero boto3 handles the four allowlisted bucket-only operations.
    command = 'sudo python3 /home/egk/homelab/reliability/backup/ceph_bucket_check.py ' + ' '.join(args)
    return subprocess.run(SSH + [command], check=check, capture_output=True, text=True)

def refresh_ceph_credentials():
    # Only the existing RGW credential file is read; never expose it in output.
    raw = run(SSH + ['sudo cat /home/egk/.passwd-s3fs'], capture_output=True, text=True).stdout
    line = next(line.strip() for line in raw.splitlines() if line.strip() and not line.startswith('#'))
    access, secret = line.split(':')[-2:]
    atomic_json(STATE / 'ceph-rgw-credentials.json', {'access': access, 'secret': secret})
    (STATE / 'ceph-rgw-credentials.json').chmod(0o600)

def initialize_ceph():
    if not (STATE / 'ceph-rgw-credentials.json').is_file():
        refresh_ceph_credentials()
    head = aws('head-bucket', '--bucket', 'immich-backups', check=False)
    if head.returncode:
        if '(404)' not in head.stderr and 'NoSuchBucket' not in head.stderr:
            raise RuntimeError('Ceph backup bucket access failed')
        aws('create-bucket', '--bucket', 'immich-backups')
    grants = json.loads(aws('get-bucket-acl', '--bucket', 'immich-backups').stdout)['Grants']
    if any(grant.get('Grantee', {}).get('Type') == 'Group' for grant in grants):
        raise RuntimeError('Ceph backup bucket is not private')
    config = aws('head-object', '--bucket', 'immich-backups', '--key', 'config', check=False)
    if config.returncode:
        if '(404)' not in config.stderr and 'NoSuchKey' not in config.stderr:
            raise RuntimeError('Ceph restic config access failed')
        restic(CEPH_REPOSITORY, 'init', stdout=subprocess.DEVNULL)
    restic(CEPH_REPOSITORY, 'snapshots', '--json', stdout=subprocess.DEVNULL)

def atomic_json(path, data):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2) + '\n')
    temp.replace(path)

def container_digest(container):
    if container not in ('immich_postgres', 'immich_server'):
        raise ValueError('Unsupported container')
    image_id = run(SSH + ['sudo docker inspect --format "{{.Image}}" ' + container], capture_output=True, text=True).stdout.strip()
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', image_id):
        raise RuntimeError('Invalid container image ID')
    digests = json.loads(run(SSH + ['sudo docker image inspect --format "{{json .RepoDigests}}" ' + image_id], capture_output=True, text=True).stdout)
    if not digests:
        raise RuntimeError('Container image has no immutable repository digest')
    return digests[0]

def capture_database(stage):
    """Hold an exported read-only snapshot for both pg_dump and asset inventory."""
    process = subprocess.Popen(SSH + ['sudo docker exec -i immich_postgres psql --username=immich --dbname=immich -X -q -A -t -v ON_ERROR_STOP=1'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        process.stdin.write('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SELECT pg_export_snapshot();\n')
        process.stdin.flush()
        snapshot = process.stdout.readline().strip()
        if not re.fullmatch(r'[0-9A-Fa-f]+-[0-9A-Fa-f]+-[0-9]+', snapshot):
            raise RuntimeError('Could not export a consistent PostgreSQL snapshot')
        db = stage / 'database.dump'
        tmp = stage / 'database.dump.tmp'
        with tmp.open('wb') as output:
            run(SSH + ['sudo docker exec immich_postgres pg_dump --username=immich --dbname=immich --format=custom --snapshot=' + snapshot], stdout=output)
        marker = 'END_INVENTORY_' + secrets.token_hex(8)
        process.stdin.write(SQL + "; SELECT '" + marker + "'; COMMIT;\n")
        process.stdin.flush()
        rows = []
        for line in process.stdout:
            if line.strip() == marker:
                break
            rows.append(line)
        else:
            raise RuntimeError('Consistent asset inventory did not complete')
        process.stdin.close()
        if process.wait(timeout=30):
            raise RuntimeError('PostgreSQL snapshot session failed')
        tmp.replace(db)
        inventory = ''.join(rows)
        (stage / 'assets.csv').write_text(inventory)
        return db, inventory
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)

def initialize():
    for path in (STATE, STAGE, HOME / 'immich-backup-restic'):
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)
    if not PASSWORD.exists():
        recovery = STATE / 'recovery-password'
        if WORKER == 'minitx' and recovery.is_file():
            shutil.copyfile(recovery, PASSWORD)
        elif (HOME / 'immich-backup-restic/config').exists():
            raise RuntimeError('Existing repository has no recovery key; refusing to generate a replacement')
        else:
            fd = os.open(PASSWORD, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as handle:
                handle.write(secrets.token_urlsafe(48) + '\n')
    PASSWORD.chmod(0o600)
    repo = REPOSITORIES[0]
    if not (Path(repo) / 'config').exists():
        restic(repo, 'init', stdout=subprocess.DEVNULL)
    restic(repo, 'snapshots', '--json', stdout=subprocess.DEVNULL)

def initialize_secondary():
    # Recovery key on another owned host, never passed in arguments or logged.
    key_command = """set -eu; umask 077; mkdir -p /home/egk/.local/state/immich-backup; chmod 700 /home/egk/.local/state/immich-backup; keytmp=$(mktemp /home/egk/.local/state/immich-backup/recovery-password.XXXXXX); trap 'rm -f "$keytmp"' EXIT; cat > "$keytmp"; if test -f /home/egk/.local/state/immich-backup/recovery-password; then cmp -s "$keytmp" /home/egk/.local/state/immich-backup/recovery-password; else mv "$keytmp" /home/egk/.local/state/immich-backup/recovery-password; fi; chmod 600 /home/egk/.local/state/immich-backup/recovery-password"""
    with PASSWORD.open('rb') as key:
        run(['ssh', *SECONDARY_OPTIONS, SECONDARY_HOST, key_command], stdin=key, stdout=subprocess.DEVNULL)
    absent = subprocess.run(['ssh', *SECONDARY_OPTIONS, SECONDARY_HOST, 'test ! -f /home/egk/immich-backup-restic/config']).returncode
    if absent not in (0, 1):
        raise RuntimeError('Cannot reach secondary backup host')
    if absent == 0:
        restic(REPOSITORIES[1], 'init', stdout=subprocess.DEVNULL)
    restic(REPOSITORIES[1], 'snapshots', '--json', stdout=subprocess.DEVNULL)

def snapshot_repository(repo, stage, kind):
    result = restic(repo, 'backup', str(stage), '--tag', 'immich', '--tag', kind, '--host', 'immich-cloudvero', '--json', capture_output=True, text=True)
    summaries = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
    snapshot = next((line['snapshot_id'] for line in summaries if line.get('message_type') == 'summary'), None)
    if not snapshot:
        raise RuntimeError('Snapshot ID missing')
    return {'repository': repo, 'snapshot_id': snapshot, 'status': 'ok', 'completed_at': time.time()}

def sanitized_failure(repo, error):
    return {'repository': repo, 'status': 'failed', 'error_type': type(error).__name__, 'error_code': getattr(error, 'returncode', None), 'completed_at': time.time()}

def mirror_report(report, kind, mandatory_ok):
    if WORKER != 'minitx' or kind != 'media':
        return
    targets = ['minitx-last-report-media.json']
    if mandatory_ok:
        targets.append('minitx-last-media.json')
    for target in targets:
        command = f'umask 077; mkdir -p /home/egk/.local/state/immich-backup; cat > /home/egk/.local/state/immich-backup/{target}.tmp && mv /home/egk/.local/state/immich-backup/{target}.tmp /home/egk/.local/state/immich-backup/{target}'
        run(['ssh', *SECONDARY_OPTIONS, SECONDARY_HOST, command], input=json.dumps(report), text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def clean_owned_staging(stage, inventory):
    """After safe snapshots, remove only stage files absent from source AND DB."""
    data = stage / 'data'
    if data != STAGE / 'media/data' or data.is_symlink():
        raise RuntimeError('Refusing unsafe staging cleanup path')
    tree = run(SSH + ["sudo find /var/lib/immich/data \\( -type f -o -type l \\) -printf '%P\\0'"], capture_output=True).stdout
    keep = {entry.decode('utf-8') for entry in tree.split(b'\0') if entry}
    for row in csv.DictReader(io.StringIO(inventory)):
        original = row['originalPath']
        for prefix in ('/usr/src/app/upload/', '/data/'):
            if original.startswith(prefix):
                keep.add(original[len(prefix):])
                break
    removed = 0
    for path in data.rglob('*'):
        if (path.is_file() or path.is_symlink()) and path.relative_to(data).as_posix() not in keep:
            path.unlink()
            removed += 1
    for path in sorted((path for path in data.rglob('*') if path.is_dir() and not path.is_symlink()), key=lambda path: len(path.parts), reverse=True):
        try:
            path.rmdir()
        except OSError:
            pass  # Nonempty directories are expected and must remain.
    return {'removed_orphan_stage_files': removed, 'checked_at': time.time()}

def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--media', action='store_true', help='Include verified local primary media')
    parser.add_argument('--source', default='/var/lib/immich/data')
    args = parser.parse_args()
    if args.source != '/var/lib/immich/data':
        parser.error('Only local primary /var/lib/immich/data is supported')
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE / 'lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        initialize()
        kind = 'media' if args.media else 'metadata-only'
        stage = STAGE / kind
        stage.mkdir(parents=True, exist_ok=True, mode=0o700)
        db, inventory = capture_database(stage)
        # Verify dump structure before considering it a candidate snapshot.
        with db.open('rb') as source:
            if source.read(5) != b'PGDMP':
                raise RuntimeError('Invalid PostgreSQL custom dump header')
        config_command = "sudo sh -c 'set -eu; set -- home/egk/homelab/.env home/egk/homelab/docker-compose.yml; for candidate in etc/systemd/system/homelab-immich.service etc/systemd/system/ceph-c250c795-7f0b-11f0-8959-3c7c3f7a0e4f@.service.d/homelab-reliability.conf; do if test -f /\"$candidate\"; then set -- \"$@\" \"$candidate\"; fi; done; tar -C / -czf - -- \"$@\"'"
        with (stage / 'deployment-config.tar.gz').open('wb') as output:
            run(SSH + [config_command], stdout=output)
        credential_refresh_error = None
        try:
            refresh_ceph_credentials()
        except Exception as error:
            # Source protection must continue when the optional cluster credential fails.
            credential_refresh_error = sanitized_failure('ceph-credentials', error)
        credentials = stage / 'private-credentials'
        credentials.mkdir(mode=0o700, exist_ok=True)
        credentials.chmod(0o700)
        for source in (PASSWORD, STATE / 'ceph-rgw-credentials.json', HOME / '.local/state/immich-monitor/api-key'):
            if source.is_file():
                target = credentials / ('monitor-api-key' if source.name == 'api-key' else source.name)
                shutil.copyfile(source, target)
                target.chmod(0o600)
        manifest = {'created_at': time.time(), 'kind': kind, 'worker': WORKER, 'worker_host': platform.node(), 'required_repositories': MANDATORY_REPOSITORIES, 'database_image': container_digest('immich_postgres'), 'immich_image': container_digest('immich_server'), 'database': 'immich', 'database_user': 'immich', 'source': args.source, 'database_sha256': hashlib.sha256(db.read_bytes()).hexdigest(), 'library_complete': False, 'database_inventory_consistent': True}
        if credential_refresh_error:
            manifest['credential_refresh_error'] = credential_refresh_error
        if args.media:
            # Fail if the source is still FUSE, or initialization markers are absent.
            run(SSH + ['sudo test -f /var/lib/immich/data/upload/.immich && fs=$(sudo findmnt -n -o FSTYPE -T /var/lib/immich/data) && test "$fs" = ext4'], stdout=subprocess.DEVNULL)
            data = stage / 'data'
            data.mkdir(exist_ok=True, mode=0o700)
            run(['rsync', '-a', '--checksum', '--no-owner', '--no-group', '--rsync-path=sudo rsync', '-e', 'ssh -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=30 -o ServerAliveCountMax=3', 'cloudvero:' + args.source + '/', str(data) + '/'])
            source_results = json.loads(run(SSH + ['sudo nice -n 10 ionice -c 3 python3 /home/egk/homelab/reliability/backup/source_asset_integrity.py'], input=inventory, capture_output=True, text=True).stdout)
            manifest['source_checked_at'] = time.time()
            atomic_json(stage / 'source-asset-integrity.json', source_results)
            source_statuses = {row['id']: row['status'] for row in source_results}
            inventory_rows = list(csv.DictReader(io.StringIO(inventory)))
            results = []
            for row in inventory_rows:
                original = row['originalPath']
                relative = None
                for prefix in ('/usr/src/app/upload/', '/data/'):
                    if original.startswith(prefix):
                        relative = original[len(prefix):]
                        break
                status = 'unsupported-path'
                if relative and not Path(relative).is_absolute() and '..' not in Path(relative).parts:
                    path = data / relative
                    if not path.is_file():
                        status = 'missing'
                    else:
                        digest = hashlib.sha1()
                        with path.open('rb') as handle:
                            for block in iter(lambda: handle.read(1024 * 1024), b''):
                                digest.update(block)
                        status = 'verified' if digest.hexdigest() == row['checksum'] else 'hash-mismatch'
                results.append(dict(row, status=status, source_status=source_statuses[row['id']], cache_recovery_available=status == 'verified' and source_statuses[row['id']] == 'missing'))
            atomic_json(stage / 'asset-integrity.json', results)
            manifest['assets'] = len(results)
            manifest['verified'] = sum(row['status'] == 'verified' for row in results)
            manifest['missing'] = sum(row['status'] == 'missing' for row in results)
            manifest['integrity_errors'] = sum(row['status'] not in ('verified', 'missing') for row in results)
            manifest['source_verified'] = sum(row['status'] == 'verified' for row in source_results)
            manifest['source_present'] = sum(row['status'] != 'missing' for row in source_results)
            manifest['source_missing'] = sum(row['status'] == 'missing' for row in source_results)
            manifest['source_integrity_errors'] = sum(row['status'] not in ('verified', 'missing') for row in source_results)
            manifest['cache_recovery_available'] = sum(row['cache_recovery_available'] for row in results)
            manifest['backup_inventory_complete'] = manifest['verified'] == manifest['assets']
            manifest['library_complete'] = manifest['source_verified'] == manifest['assets'] and manifest['backup_inventory_complete']
            manifest['primary_read_integrity_healthy'] = manifest['source_integrity_errors'] == 0
            manifest['primary_inventory_complete'] = manifest['source_missing'] == 0 and manifest['primary_read_integrity_healthy']
            if manifest['integrity_errors'] or manifest['source_integrity_errors']:
                failed = dict(manifest, snapshots=[], mandatory_repositories_healthy=False, backup_attempt_status='failed-integrity-check', repository_status=[{'repository': repo, 'status': 'not-attempted', 'reason': 'integrity-check-failed'} for repo in [*REPOSITORIES, CEPH_REPOSITORY]])
                try:
                    mirror_report(failed, kind, False)
                except Exception as error:
                    failed['desktop_report_mirror_error'] = sanitized_failure('desktop-report-mirror', error)
                atomic_json(stage / 'manifest.json', failed)
                atomic_json(STATE / ('last-report-' + kind + '.json'), failed)
                print(json.dumps(failed, indent=2))
                raise RuntimeError('Original asset integrity mismatch; no successful backup status written')
        atomic_json(stage / 'manifest.json', manifest)
        snapshots = [snapshot_repository(REPOSITORIES[0], stage, kind)]
        statuses = list(snapshots)
        atomic_json(STATE / ('last-local-' + kind + '.json'), dict(manifest, snapshots=list(snapshots)))
        try:
            initialize_secondary()
            secondary = snapshot_repository(REPOSITORIES[1], stage, kind)
            snapshots.append(secondary)
            statuses.append(secondary)
        except Exception as error:
            statuses.append(sanitized_failure(REPOSITORIES[1], error))
        try:
            with ceph_tunnel():
                initialize_ceph()
                cluster = snapshot_repository(CEPH_REPOSITORY, stage, kind)
                snapshots.append(cluster)
                statuses.append(cluster)
        except Exception as error:
            statuses.append(sanitized_failure(CEPH_REPOSITORY, error))
        mandatory_ok = all(any(status['repository'] == repo and status['status'] == 'ok' for status in statuses) for repo in MANDATORY_REPOSITORIES)
        report = dict(manifest, snapshots=snapshots, repository_status=statuses, mandatory_repositories_healthy=mandatory_ok, cluster_copy_degraded=not any(status['repository'] == CEPH_REPOSITORY and status['status'] == 'ok' for status in statuses))
        if args.media and mandatory_ok:
            try:
                report['staging_cleanup'] = clean_owned_staging(stage, inventory)
            except Exception as error:
                report['staging_cleanup_error'] = sanitized_failure('owned-staging', error)
        try:
            mirror_report(report, kind, mandatory_ok)
        except Exception as error:
            report['desktop_report_mirror_error'] = sanitized_failure('desktop-report-mirror', error)
        atomic_json(STATE / ('last-report-' + kind + '.json'), report)
        if mandatory_ok:
            atomic_json(STATE / ('last-' + kind + '.json'), report)
        print(json.dumps(report, indent=2))
        if not mandatory_ok:
            raise RuntimeError('Independent secondary backup failed; successful local snapshot preserved')

if __name__ == '__main__':
    if '-h' in sys.argv or '--help' in sys.argv:
        main()
    else:
        os.umask(0o077)
        STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
        attempt = {'started_at': time.time(), 'kind': 'media' if '--media' in sys.argv else 'metadata-only', 'status': 'running'}
        atomic_json(STATE / 'last-attempt.json', attempt)
        try:
            main()
        except Exception as error:
            attempt.update(completed_at=time.time(), status='failed', error_type=type(error).__name__)
            atomic_json(STATE / 'last-attempt.json', attempt)
            raise
        else:
            attempt.update(completed_at=time.time(), status='ok')
            atomic_json(STATE / 'last-attempt.json', attempt)
