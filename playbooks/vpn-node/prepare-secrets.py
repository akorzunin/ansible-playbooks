#!/usr/bin/env python3
"""Create one node's persistent credentials directly in Vault, never replacing them."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('vpn_credentials', ROOT / 'roles/vpn_node/files/credentials.py')
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)


def prepare(output, password):
    if output.exists() or output.is_symlink():
        raise FileExistsError('Refusing to replace node credentials')
    with tempfile.TemporaryDirectory(prefix='vpn-node-keys-') as work:
        key = Path(work) / 'probe'
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)],
                       check=True, capture_output=True)
        data = {
            'vpn_node_credentials': shared.credentials(),
            'vpn_node_hysteria2_password': secrets.token_urlsafe(32),
            'vpn_node_probe_private_key': key.read_text(),
            'vpn_node_probe_public_key': key.with_suffix('.pub').read_text(),
        }
    encrypted = subprocess.run([
        'ansible-vault', 'encrypt', '--vault-password-file', str(password), '--output', '-',
    ], input=json.dumps(data).encode(), check=True, capture_output=True).stdout
    if not encrypted.startswith(b'$ANSIBLE_VAULT;'):
        raise ValueError('Vault did not produce ciphertext')
    with os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
        stream.write(encrypted)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--vault-password-file', type=Path, default=ROOT / '.ansible_pass')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,62}', args.node):
        parser.error('Invalid node name')
    os.umask(0o077)
    try:
        prepare(args.output or ROOT / 'node' / args.node / 'vpn.vault.yaml', args.vault_password_file)
    except (OSError, ValueError, subprocess.SubprocessError):
        parser.exit(1, 'Credential preparation failed; existing credentials are never replaced.\n')
    print('Encrypted node credentials created; back up the Vault and transfer its password separately.')
