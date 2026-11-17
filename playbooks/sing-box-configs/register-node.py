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


def managed_tags(node):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,62}', node):
        raise ValueError('Invalid node name')
    return {node + '-' + kind for kind in
            ('ssh', 'naive', 'vless', 'hysteria2', 'vless-via-naive', 'ssh-via-workstation')}


def merge(data, node, outbounds, default=None):
    managed = managed_tags(node)
    expected = {node + '-' + kind for kind in ('ssh', 'naive', 'vless')}
    tags = {o['tag'] for o in outbounds}
    dynamic = bool(re.fullmatch(r'dyn[1-9][0-9]*', node))
    allowed = (expected,) if dynamic else (expected, expected | {node + '-hysteria2'})
    if len(outbounds) != len(tags) or tags not in allowed:
        raise ValueError('Expected SSH, Naive and VLESS, with optional Hysteria 2')
    if any(o['tag'] != node + '-' + o['type'] for o in outbounds):
        raise ValueError('Connection types and tags disagree')
    derived = {node + '-ssh-via-workstation'}
    if not dynamic:
        derived.add(node + '-vless-via-naive')
    if default is not None and default not in tags | derived:
        raise ValueError('Default must belong to this node')
    result = copy.deepcopy(data)
    secrets = result['sing_box_secrets']
    secrets['extra_outbounds'] = [o for o in secrets.get('extra_outbounds', [])
                                if o['tag'] not in managed] + copy.deepcopy(outbounds)
    if default is not None:
        secrets['default_outbound'] = default
    elif dynamic and secrets.get('default_outbound') in {node + '-hysteria2', node + '-vless-via-naive'}:
        secrets['default_outbound'] = node + '-vless'
    return result


def remove(data, node, fallback=None):
    managed = managed_tags(node)
    result = copy.deepcopy(data)
    secrets = result['sing_box_secrets']
    secrets['extra_outbounds'] = [o for o in secrets.get('extra_outbounds', []) if o['tag'] not in managed]
    if secrets.get('default_outbound') in managed:
        if not fallback or fallback in managed:
            raise ValueError('A surviving default is required before removing this node')
        secrets['default_outbound'] = fallback
    return result


def migrate_cherry(data, node):
    """One-time dyn1 alias migration, in the same transaction as registration/removal."""
    if node != 'dyn1':
        return data
    result = copy.deepcopy(data)
    secrets = result['sing_box_secrets']
    legacy = managed_tags('cherry')
    default = secrets.get('default_outbound')
    if default in legacy:
        suffix = default.removeprefix('cherry-')
        if suffix in ('hysteria2', 'vless-via-naive'):
            suffix = 'vless'
        secrets['default_outbound'] = 'dyn1-' + suffix
    secrets['extra_outbounds'] = [o for o in secrets.get('extra_outbounds', []) if o['tag'] not in legacy]
    # Other chains may refer to the renamed node as their carrier.
    for outbound in secrets['extra_outbounds']:
        if outbound.get('detour') in legacy:
            suffix = outbound['detour'].removeprefix('cherry-')
            if suffix in ('hysteria2', 'vless-via-naive'):
                suffix = 'vless'
            outbound['detour'] = 'dyn1-' + suffix
    return result


def register(vault, password, node, outbounds, default, migrate=False):
    # One active controller; use shared locking before allowing concurrent publishers.
    original = vault.read_bytes()
    data = yaml.safe_load(subprocess.run([
        'ansible-vault', 'view', '--vault-password-file', str(password), str(vault),
    ], check=True, capture_output=True).stdout)
    source = migrate_cherry(data, node) if migrate else data
    updated = remove(source, node, default) if outbounds is None else merge(source, node, outbounds, default)
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
    parser.add_argument('--migrate-cherry', action='store_true',
                        help='For dyn1 only, retire legacy cherry-* aliases and remap their default atomically')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--outbounds-file', type=Path)
    action.add_argument('--remove', action='store_true')
    parser.add_argument('--default', help='New node default, or removal fallback; omitted registration preserves the default')
    parser.add_argument('--vault-file', type=Path, default=Path(__file__).with_name('secrets.vault.yaml'))
    parser.add_argument('--vault-password-file', type=Path, default=ROOT / '.ansible_pass')
    args = parser.parse_args()
    os.umask(0o077)
    changed = register(args.vault_file, args.vault_password_file, args.node,
                       None if args.remove else json.loads(args.outbounds_file.read_text()), args.default, args.migrate_cherry)
    print('Node profile source updated.' if changed else 'Node profile source unchanged.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        raise SystemExit('Node registration failed; inspect private inputs locally. No credentials were printed.')
