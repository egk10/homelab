#!/usr/bin/env python3
"""Read-only, bounded SHA1 sample of selected originals in one Ceph snapshot."""
import argparse
import csv
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import resource
import stat
import subprocess
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'backup'))
from immich_backup import STATE, STAGE, WORKER, CEPH_REPOSITORY, ceph_tunnel, restic

MAX_BYTES = 32 * 1024 * 1024
TIMEOUT = 180
CURRENT_STEP = 'validation'


class SampleError(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise SampleError('invalid_cli_arguments')


def checked_path(path, *, existing=False):
    path = Path(os.path.abspath(path))
    for component in [*reversed(path.parents), path]:
        if component.is_symlink():
            raise SampleError('local_path_is_symlink')
    if existing:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise SampleError('input_not_private_regular_file')
    elif not path.parent.is_dir() or (path.exists() and not path.is_file()):
        raise SampleError('report_destination_invalid')
    return path


def selection_rows(path):
    path = checked_path(path, existing=True)
    if path.stat().st_size > MAX_BYTES:
        raise SampleError('selection_too_large')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, list) or not data:
        raise SampleError('selection_empty_or_invalid')
    selected = {}
    for row in data:
        if not isinstance(row, dict):
            raise SampleError('selection_row_invalid')
        asset_id, month = row.get('id'), row.get('month')
        if not isinstance(asset_id, str) or str(uuid.UUID(asset_id)) != asset_id:
            raise SampleError('selection_id_invalid')
        if not isinstance(month, str) or not re.fullmatch(r'[0-9]{4}-(0[1-9]|1[0-2])', month):
            raise SampleError('selection_month_invalid')
        if asset_id in selected and selected[asset_id] != month:
            raise SampleError('selection_month_conflict')
        selected[asset_id] = month
    return selected


def relative_original(original):
    if not isinstance(original, str) or any(ord(char) < 32 or ord(char) == 127 for char in original) or '\\' in original:
        raise SampleError('original_path_invalid')
    for prefix in ('/usr/src/app/upload/', '/data/'):
        if original.startswith(prefix):
            relative = original[len(prefix):]
            break
    else:
        raise SampleError('original_path_prefix_invalid')
    parts = relative.split('/')
    if not relative or PurePosixPath(relative).is_absolute() or any(part in ('', '.', '..') for part in parts):
        raise SampleError('original_path_unsafe')
    return PurePosixPath(relative)


def file_limit():
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_BYTES, MAX_BYTES))


def bounded_restic(target, *args):
    cache = target.parent / 'cache'
    cache.mkdir(mode=0o700, exist_ok=True)
    with target.open('xb') as output:
        os.chmod(target, 0o600)
        restic(CEPH_REPOSITORY, '--no-lock', '--cache-dir', str(cache), *args,
               stdout=output, stderr=subprocess.DEVNULL, timeout=TIMEOUT,
               preexec_fn=file_limit)
    if target.stat().st_size > MAX_BYTES:
        raise SampleError('snapshot_file_too_large')


def snapshot_nodes(path):
    nodes = {}
    with path.open(encoding='utf-8') as source:
        for line in source:
            row = json.loads(line)
            if isinstance(row, dict) and row.get('struct_type') == 'node':
                name = row.get('path')
                if not isinstance(name, str) or name in nodes:
                    raise SampleError('snapshot_listing_invalid')
                nodes[name] = row
    return nodes


def regular_snapshot_file(nodes, path):
    path = PurePosixPath(path)
    node = nodes.get(str(path))
    if node is None:
        return None
    if node.get('type') != 'file':
        raise SampleError('snapshot_original_not_regular')
    for parent in path.parents:
        ancestor = nodes.get(str(parent))
        if ancestor is not None and ancestor.get('type') != 'dir':
            raise SampleError('snapshot_ancestor_not_directory')
    size = node.get('size')
    if type(size) is not int or size < 0:
        raise SampleError('snapshot_size_invalid')
    return size


def verify(snapshot, selected, scratch, progress=lambda step: None):
    stage = PurePosixPath(str(STAGE / 'media'))
    listing = scratch / 'listing'
    progress('metadata_ls')
    bounded_restic(listing, 'ls', '--json', snapshot, str(stage))
    nodes = snapshot_nodes(listing)
    for name in ('manifest.json', 'assets.csv'):
        size = regular_snapshot_file(nodes, stage / name)
        if size is None or size > MAX_BYTES:
            raise SampleError('snapshot_metadata_missing_or_large')
        progress('manifest_dump' if name == 'manifest.json' else 'inventory_dump')
        bounded_restic(scratch / name, 'dump', snapshot, str(stage / name))
    progress('inventory_validation')
    manifest = json.loads((scratch / 'manifest.json').read_text())
    if (not isinstance(manifest, dict) or manifest.get('kind') != 'media'
            or manifest.get('database_inventory_consistent') is not True):
        raise SampleError('snapshot_manifest_scope_invalid')
    with (scratch / 'assets.csv').open(newline='', encoding='utf-8') as source:
        reader = csv.DictReader(source)
        if not {'id', 'originalPath', 'checksum'} <= set(reader.fieldnames or []):
            raise SampleError('snapshot_inventory_schema_invalid')
        rows = list(reader)
    if type(manifest.get('assets')) is not int or manifest['assets'] != len(rows):
        raise SampleError('snapshot_inventory_count_mismatch')
    seen, matched, candidates = set(), 0, {}
    for row in rows:
        asset_id = row['id']
        if asset_id in seen:
            raise SampleError('snapshot_inventory_duplicate_id')
        seen.add(asset_id)
        if asset_id not in selected:
            continue
        matched += 1
        relative = relative_original(row['originalPath'])
        checksum = row['checksum']
        if not re.fullmatch(r'[a-f0-9]{40}', checksum):
            raise SampleError('snapshot_checksum_invalid')
        if relative.suffix.lower() not in ('.jpg', '.jpeg'):
            continue
        path = stage / 'data' / relative
        candidates.setdefault(selected[asset_id], []).append((asset_id, path, checksum))
    if not candidates:
        raise SampleError('no_available_selected_jpeg')
    samples, listed_parents = [], set()
    oversized = missing = 0
    for month in sorted(candidates):
        chosen = None
        for asset_id, path, checksum in sorted(candidates[month], key=lambda row: row[0]):
            if path.parent not in listed_parents:
                parent_listing = scratch / f'sample-listing-{len(listed_parents)}'
                progress('sample_parent_ls')
                bounded_restic(parent_listing, 'ls', '--json', snapshot, str(path.parent))
                nodes.update(snapshot_nodes(parent_listing))
                listed_parents.add(path.parent)
            size = regular_snapshot_file(nodes, path)
            if size is None:
                missing += 1
                continue
            if size > MAX_BYTES:
                oversized += 1
                continue
            chosen = (asset_id, path, checksum, size)
            break
        if chosen is None:
            continue
        asset_id, path, checksum, size = chosen
        index = len(samples)
        output = scratch / f'original-{index}'
        progress('original_dump')
        bounded_restic(output, 'dump', snapshot, str(path))
        progress('original_hash_compare')
        digest = hashlib.sha1()
        with output.open('rb') as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(block)
        if output.stat().st_size != size or digest.hexdigest() != checksum:
            raise SampleError('original_sha1_or_size_mismatch')
        samples.append({'id': asset_id, 'month': month, 'bytes': size, 'sha1_passed': True})
        if len(samples) == 3:
            break
    if not samples:
        raise SampleError('no_available_selected_jpeg')
    return {'snapshot_id': snapshot, 'scope': 'selected_original_sample_only',
            'selection_count': len(selected), 'snapshot_asset_count': len(rows),
            'selected_in_snapshot_count': matched, 'candidate_months': sorted(candidates),
            'sampled_months': [row['month'] for row in samples], 'samples_count': len(samples),
            'oversized_candidates_skipped': oversized, 'sha1_passed': True,
            'missing_candidates_skipped': missing, 'parent_listings_count': len(listed_parents),
            'full_restore_verified': False, 'samples': samples, 'step': 'complete'}


def write_report(path, report):
    # The temporary file is ours, private, and on the same filesystem as its target.
    handle, temporary = tempfile.mkstemp(prefix='.immich-sample-report-', dir=path.parent)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as output:
            json.dump(report, output, indent=2)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        checked_path(path)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def sanitized_error(error):
    if isinstance(error, SampleError):
        return str(error)
    for error_type, code in (
        (subprocess.TimeoutExpired, 'restic_timeout'),
        (subprocess.CalledProcessError, 'restic_read_failed'),
        (json.JSONDecodeError, 'invalid_json'),
        (OSError, 'local_io_failed'),
        (ValueError, 'invalid_value'),
    ):
        if isinstance(error, error_type):
            return code
    return 'sample_verification_failed'


def main():
    os.umask(0o077)
    parser = Parser(description=__doc__)
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--selection', required=True)
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    if WORKER != 'workstation':
        raise SampleError('workstation_role_required')
    if not re.fullmatch(r'[a-f0-9]{64}', args.snapshot):
        raise SampleError('snapshot_id_invalid')
    report_path = checked_path(args.report)
    selection_path = checked_path(args.selection, existing=True)
    if report_path == selection_path:
        raise SampleError('report_cannot_replace_selection')
    report = {'snapshot_id': args.snapshot, 'scope': 'selected_original_sample_only',
              'samples_count': 0, 'sha1_passed': False, 'full_restore_verified': False}
    def set_step(step):
        global CURRENT_STEP
        CURRENT_STEP = step
        report.update(step=step, tested_at=time.time())
        write_report(report_path, report)
    try:
        set_step('selection_validation')
        selected = selection_rows(selection_path)
        report['selection_count'] = len(selected)
        with (STATE / 'lock').open('a') as lock:
            set_step('waiting_local_lock')
            fcntl.flock(lock, fcntl.LOCK_EX)
            with tempfile.TemporaryDirectory(prefix='immich-phone-backup-sample-', dir=STATE) as temporary:
                os.chmod(temporary, 0o700)
                set_step('ceph_tunnel')
                with ceph_tunnel():
                    report = verify(args.snapshot, selected, Path(temporary), set_step)
    except Exception as error:
        report.update(tested_at=time.time(), code=sanitized_error(error))
        write_report(report_path, report)
        raise
    report.update(tested_at=time.time(), code='ok')
    write_report(report_path, report)
    print(json.dumps({key: report[key] for key in ('code', 'selection_count',
        'snapshot_asset_count', 'selected_in_snapshot_count', 'sampled_months',
        'samples_count', 'sha1_passed', 'step')}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'code': sanitized_error(error), 'step': CURRENT_STEP, 'sha1_passed': False}))
        sys.exit(1)
