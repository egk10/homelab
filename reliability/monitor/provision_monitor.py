#!/usr/bin/env python3
"""Provision a quota-limited test account, then create its key through the API.

The SQL bootstrap creates only this service's account; existing users are untouched.
Credentials stay in mode-600 files and are never logged.
"""
import json
import os
from pathlib import Path
import secrets
import subprocess

import bcrypt
import requests


def main():
    os.umask(0o077)
    state = Path('/home/egk/.local/state/immich-monitor')
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    config = state / 'bootstrap.json'
    if config.exists():
        account = json.loads(config.read_text())
    else:
        account = {'email': 'immich-monitor@homelab.invalid', 'password': secrets.token_urlsafe(36)}
        config.write_text(json.dumps(account))
        config.chmod(0o600)
    password_hash = bcrypt.hashpw(account['password'].encode(), bcrypt.gensalt(rounds=10)).decode()
    query = '''INSERT INTO "user" (email,password,name,"isAdmin","shouldChangePassword","quotaSizeInBytes")
        VALUES ('immich-monitor@homelab.invalid','%s','Homelab service monitor',false,false,10485760)
        ON CONFLICT (email) DO NOTHING;''' % password_hash
    # Hash only crosses SSH; no plaintext password or key reaches shell arguments.
    result = subprocess.run(['ssh', '-o', 'BatchMode=yes', 'cloudvero',
                             'docker exec -i immich_postgres psql -U immich -d immich -q -v ON_ERROR_STOP=1'],
                            input=query, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('Service-account bootstrap failed; private database error not printed')
    key_path = state / 'api-key'
    if key_path.exists():
        print('Dedicated monitor account and API key already provisioned')
        return
    client = requests.Session()
    login = client.post('https://immich.velociraptor-scylla.ts.net/api/auth/login', json=account, timeout=20)
    if login.status_code != 201:
        raise RuntimeError(f'Service-account login returned HTTP {login.status_code}')
    token = login.json().get('accessToken')
    if token:
        client.headers['Authorization'] = 'Bearer ' + token
    response = client.post('https://immich.velociraptor-scylla.ts.net/api/api-keys',
                           json={'name': 'homelab-synthetic-monitor',
                                 'permissions': ['asset.upload', 'asset.download', 'asset.delete']}, timeout=20)
    if response.status_code != 201:
        raise RuntimeError(f'Scoped API-key creation returned HTTP {response.status_code}')
    payload = response.json()
    secret = payload.get('secret')
    if not isinstance(secret, str) or not secret:
        raise RuntimeError('API did not return the expected one-time secret')
    key_path.write_text(secret + '\n')
    key_path.chmod(0o600)
    print('Dedicated non-admin monitor account provisioned with 10 MiB quota and three API scopes')


if __name__ == '__main__':
    main()
