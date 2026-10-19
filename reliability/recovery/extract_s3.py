#!/usr/bin/env python3
"""Preserve reachable S3 data locally; verify every DB original's SHA1.

Never delete source objects or database rows. The manifest is private.
"""
import argparse
import collections
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import time

import boto3
from botocore.config import Config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--originals-only", action="store_true")
    parser.add_argument("--asset-ids-file", help="Private JSON list of asset IDs to retry")
    args = parser.parse_args()
    destination = Path(args.destination)
    destination.mkdir(parents=True, exist_ok=True)
    credential = next(line.strip() for line in Path("/home/egk/.passwd-s3fs").read_text().splitlines()
                      if line.strip() and not line.startswith("#"))
    access, secret = credential.split(":")[-2:]
    client = boto3.client("s3", endpoint_url="http://127.0.0.1:7480",
                          aws_access_key_id=access, aws_secret_access_key=secret,
                          region_name="us-east-1", config=Config(
                              max_pool_connections=8, connect_timeout=5, read_timeout=60,
                              retries={"max_attempts": 2}, s3={"addressing_style": "path"}))
    query = '''select coalesce(json_agg(t),'[]'::json) from (
        select id, "originalPath" as path, encode(checksum,'hex') as checksum,
        "originalFileName" as original_name from asset order by id) t;'''
    rows = json.loads(subprocess.check_output([
        "docker", "exec", "immich_postgres", "psql", "-U", "immich", "-d", "immich", "-Atc", query], text=True))
    if args.asset_ids_file:
        ids = json.loads(Path(args.asset_ids_file).read_text())
        if not isinstance(ids, list) or not all(isinstance(value, str) for value in ids):
            raise RuntimeError("Asset selection must be a JSON list of IDs")
        wanted = set(ids)
        if not wanted.issubset({row["id"] for row in rows}):
            raise RuntimeError("Unknown asset in retry selection")
        rows = [row for row in rows if row["id"] in wanted]
    prefix = "/usr/src/app/upload/"
    originals = {}
    for row in rows:
        if not row["path"].startswith(prefix):
            raise RuntimeError("Unexpected original path; refusing unsafe extraction")
        key = row["path"][len(prefix):]
        originals[key] = row
    keys = set(originals)
    listed = set()
    sizes = {}
    if not args.originals_only:
        for page in client.get_paginator("list_objects_v2").paginate(Bucket="immich-uploads"):
            for item in page.get("Contents", []):
                listed.add(item["Key"])
                sizes[item["Key"]] = item["Size"]
    keys.update(listed)
    started = time.time()

    def extract(key):
        result = {"key": key, "original": key in originals}
        if key in originals:
            result.update(originals[key])
        path = PurePosixPath(key)
        if path.is_absolute() or ".." in path.parts:
            return {**result, "status": "unsafe_key"}
        if key.endswith("/"):
            (destination / key).mkdir(parents=True, exist_ok=True)
            return {**result, "status": "directory"}
        target = destination / key
        target.parent.mkdir(parents=True, exist_ok=True)
        expected = originals.get(key, {}).get("checksum")
        if target.is_file() and not expected and key in sizes and target.stat().st_size == sizes[key]:
            return {**result, "status": "copied", "bytes": target.stat().st_size}
        if target.is_file() and expected:
            digest = hashlib.sha1()
            with target.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() == expected:
                return {**result, "status": "verified", "bytes": target.stat().st_size}
        temp = target.with_name(target.name + ".preserving-part")
        try:
            body = client.get_object(Bucket="immich-uploads", Key=key)["Body"]
            digest = hashlib.sha1()
            count = 0
            try:
                with temp.open("wb") as stream:
                    for chunk in body.iter_chunks(chunk_size=1024 * 1024):
                        stream.write(chunk)
                        digest.update(chunk)
                        count += len(chunk)
                    stream.flush()
                    os.fsync(stream.fileno())
            finally:
                body.close()
            actual = digest.hexdigest()
            if expected and actual != expected:
                temp.rename(temp.with_suffix(temp.suffix + ".checksum-mismatch"))
                return {**result, "status": "checksum_mismatch", "bytes": count}
            temp.replace(target)
            return {**result, "status": "verified" if expected else "copied", "bytes": count, "sha1": actual}
        except Exception as error:
            temp.unlink(missing_ok=True)
            code = (getattr(error, "response", None) or {}).get("ResponseMetadata", {}).get("HTTPStatusCode")
            return {**result, "status": "missing" if code == 404 else "error",
                    "error_type": type(error).__name__, "http_status": code}

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(extract, sorted(keys)):
            results.append(result)
            if len(results) % 100 == 0:
                print(json.dumps({"processed": len(results), "total": len(keys),
                                  "seconds": round(time.time() - started)}), flush=True)
    report = {"created_at": time.time(), "source": "ceph-rgw/immich-uploads",
              "database_assets": len(rows), "listed_keys": len(listed), "results": results}
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2))
    report_path.chmod(0o600)
    summary = collections.Counter(r["status"] for r in results)
    original_summary = collections.Counter(r["status"] for r in results if r["original"])
    print(json.dumps({"files": dict(summary), "originals": dict(original_summary),
                      "bytes_copied": sum(r.get("bytes", 0) for r in results),
                      "seconds": round(time.time() - started)}), flush=True)
    if any(r["status"] in ("checksum_mismatch", "unsafe_key", "error") for r in results if r["original"]):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
