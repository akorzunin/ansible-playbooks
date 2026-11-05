#!/usr/bin/env python3
"""Idempotently register one verified VPN node in the shared encrypted profile source."""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

import yaml

import generate

ROOT = Path(__file__).resolve().parents[2]


def merge(data, node, outbounds, default):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,62}', node):
        raise ValueError('Invalid node name')
    expected = {node + '-' + kind for kind in ('ssh', 'naive', 'vless')}
    tags = {o['tag'] for o in outbounds}
    if len(outbounds) != len(tags) or tags not in (expected, expected | {node + '-hysteria2'}):
        raise ValueError('Expected SSH, Naive and VLESS, with optional Hysteria 2')
    if any(o['tag'] != node + '-' + o['type'] for o in outbounds):
        raise ValueError('Connection types and tags disagree')
    managed = expected | {node + '-hysteria2', node + '-vless-via-naive', node + '-ssh-via-workstation'}
    if default not in tags | {node + '-vless-via-naive', node + '-ssh-via-workstation'}:
        raise ValueError('Default must belong to this node')
    result = copy.deepcopy(data)
    secrets = result['sing_box_secrets']
    secrets['extra_outbounds'] = [o for o in secrets.get('extra_outbounds', [])
                                if o['tag'] not in managed] + copy.deepcopy(outbounds)
    secrets['default_outbound'] = default
    return result


def register(vault, password, node, outbounds, default):
    # One active controller; use shared locking before allowing concurrent publishers.
    original = vault.read_bytes()
    data = yaml.safe_load(subprocess.run([
        'ansible-vault', 'view', '--vault-password-file', str(password), str(vault),
    ], check=True, capture_output=True).stdout)
    updated = merge(data, node, outbounds, default)
    secrets = updated['sing_box_secrets']
    # Validate every platform and derived selector before committing encrypted inputs.
    with tempfile.TemporaryDirectory(prefix='vpn-node-register-') as work:
        generate.generate(Path(work), secrets['connections'], secrets['tokens'],
                          secrets['extra_outbounds'], secrets['default_outbound'])
    if updated == data:
        return False
    encrypted = subprocess.run([
        'ansible-vault', 'encrypt', '--vault-password-file', str(password), '--output', '-',
    ], input=yaml.safe_dump(updated, sort_keys=False).encode(), check=True, capture_output=True).stdout
    if not encrypted.startswith(b'$ANSIBLE_VAULT;'):
        raise ValueError('Vault did not produce ciphertext')
    backups = vault.parent / 'private'
    backups.mkdir(mode=0o700, exist_ok=True)
    backup = backups / (node + '-before-registration.vault.yaml')
    if not backup.exists():
        with backup.open('xb') as stream:
            stream.write(original)
    generate.private_write(vault, encrypted.decode())
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', required=True)
    parser.add_argument('--outbounds-file', type=Path, required=True)
    parser.add_argument('--default', required=True)
    parser.add_argument('--vault-file', type=Path, default=Path(__file__).with_name('secrets.vault.yaml'))
    parser.add_argument('--vault-password-file', type=Path, default=ROOT / '.ansible_pass')
    args = parser.parse_args()
    os.umask(0o077)
    changed = register(args.vault_file, args.vault_password_file, args.node,
                       json.loads(args.outbounds_file.read_text()), args.default)
    print('Node profile source updated.' if changed else 'Node profile source unchanged.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        raise SystemExit('Node registration failed; inspect private inputs locally. No credentials were printed.')
