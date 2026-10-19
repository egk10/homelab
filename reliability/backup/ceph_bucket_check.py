#!/usr/bin/env python3
"""Cloudvero-local boto3 fallback; never outputs RGW credentials."""
import argparse
import json
from pathlib import Path
import sys
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

parser = argparse.ArgumentParser()
parser.add_argument('operation', choices=('head-bucket', 'create-bucket', 'get-bucket-acl', 'head-object'))
parser.add_argument('--bucket', choices=('immich-backups',), required=True)
parser.add_argument('--key', choices=('config',))
args = parser.parse_args()
if (args.operation == 'head-object') != (args.key == 'config'):
    parser.error('Object operation is restricted to the restic config key')
line = next(line.strip() for line in Path('/home/egk/.passwd-s3fs').read_text().splitlines() if line.strip() and not line.startswith('#'))
access, secret = line.split(':')[-2:]
client = boto3.client('s3', endpoint_url='http://127.0.0.1:7480', region_name='us-east-1', aws_access_key_id=access, aws_secret_access_key=secret, config=Config(connect_timeout=10, read_timeout=60, retries={'max_attempts': 2}, s3={'addressing_style': 'path'}))
params = {'Bucket': args.bucket}
if args.key:
    params['Key'] = args.key
try:
    result = getattr(client, args.operation.replace('-', '_'))(**params)
    print(json.dumps(result, default=str))
except ClientError as error:
    code = error.response.get('ResponseMetadata', {}).get('HTTPStatusCode')
    print('(' + str(code) + ')', file=sys.stderr)
    raise SystemExit(1)
