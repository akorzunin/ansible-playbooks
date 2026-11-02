"""Per-node credentials are encrypted, complete, and never silently rotated."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('prepare_node_secrets', Path(__file__).with_name('prepare-secrets.py'))
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class NodeSecretsTests(unittest.TestCase):
    @unittest.skipUnless(all(shutil.which(x) for x in ['ansible-vault', 'openssl', 'ssh-keygen']), 'Tools unavailable')
    def test_encrypted_roundtrip_and_refusal_to_regenerate(self):
        with tempfile.TemporaryDirectory() as work:
            directory = Path(work)
            password = directory / 'password'
            password.write_text('fixture-vault-password')
            password.chmod(0o600)
            vault = directory / 'node.vault.yaml'
            prepare.prepare(vault, password)
            encrypted = vault.read_bytes()
            self.assertTrue(encrypted.startswith(b'$ANSIBLE_VAULT;'))
            self.assertEqual(vault.stat().st_mode & 0o777, 0o600)
            data = json.loads(subprocess.run([
                'ansible-vault', 'view', '--vault-password-file', str(password), str(vault),
            ], check=True, capture_output=True).stdout)
            self.assertGreaterEqual(len(data['vpn_node_hysteria2_password']), 32)
            self.assertEqual(len(data['vpn_node_credentials']['reality_public_key']), 43)
            key = directory / 'probe'
            key.write_text(data['vpn_node_probe_private_key'])
            key.chmod(0o600)
            public = subprocess.run(['ssh-keygen', '-y', '-f', str(key)], check=True, capture_output=True).stdout.decode()
            self.assertEqual(public.split()[:2], data['vpn_node_probe_public_key'].split()[:2])
            with patch.object(prepare.shared, 'credentials', side_effect=AssertionError('Must not rotate')):
                with self.assertRaises(FileExistsError):
                    prepare.prepare(vault, password)
            self.assertEqual(vault.read_bytes(), encrypted)
            link = directory / 'link.vault.yaml'
            os.symlink(directory / 'missing-target', link)
            with self.assertRaises(FileExistsError):
                prepare.prepare(link, password)
