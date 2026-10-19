#!/usr/bin/env python3
import subprocess, sys

IMAGE = 'quay.io/ceph/ceph@sha256:af0c5903e901e329adabe219dfc8d0c3efc1f05102a753902f33ee16c26b6cee'
def ceph(*args, input=None):
    result = subprocess.run(['docker', 'run', '--rm', '-i', '--network', 'host', '-v', '/etc/ceph:/etc/ceph:ro', '--entrypoint', 'ceph', IMAGE, *args], input=input, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout
if __name__ == '__main__':
    print(ceph(*sys.argv[1:]), end='')
