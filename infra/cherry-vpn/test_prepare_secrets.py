"""Credential preparation stays local, encrypted, and idempotently refuses replacement."""
import base64
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import uuid

spec = importlib.util.spec_from_file_location("prepare_secrets", Path(__file__).with_name("prepare-secrets.py"))
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


@unittest.skipUnless(shutil.which("openssl"), "OpenSSL unavailable")
class CredentialTests(unittest.TestCase):
    def test_generated_keys_match_and_credentials_are_random(self):
        first, second = prepare.credentials(), prepare.credentials()
        self.assertEqual(uuid.UUID(first["vless_uuid"]).version, 4)
        self.assertRegex(first["naive_password"], r"^[A-Za-z0-9_-]{43}$")
        self.assertRegex(first["reality_short_id"], r"^[0-9a-f]{16}$")
        self.assertNotEqual(first["naive_password"], second["naive_password"])
        self.assertNotEqual(first["reality_private_key"], second["reality_private_key"])
        private = bytes.fromhex("302e020100300506032b656e04220420") + base64.urlsafe_b64decode(first["reality_private_key"] + "=")
        public = subprocess.run(
            ["openssl", "pkey", "-inform", "DER", "-pubout", "-outform", "DER"],
            input=private, capture_output=True, check=True,
        ).stdout
        self.assertEqual(base64.urlsafe_b64encode(public[-32:]).decode().rstrip("="), first["reality_public_key"])

    @unittest.skipUnless(shutil.which("ansible-vault"), "Ansible Vault unavailable")
    def test_only_encrypted_file_is_written_and_existing_credentials_are_preserved(self):
        with tempfile.TemporaryDirectory() as work:
            directory = Path(work)
            password = directory / "password"
            password.write_text("offline-test-password\n")
            output = directory / "secrets.vault.yaml"
            prepare.prepare(output, password)
            before = output.read_bytes()
            self.assertTrue(before.startswith(b"$ANSIBLE_VAULT;"))
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertEqual({p.name for p in directory.iterdir()}, {"password", "secrets.vault.yaml"})
            result = subprocess.run(
                ["ansible-vault", "view", "--vault-password-file", str(password), str(output)],
                capture_output=True, check=True,
            )
            data = json.loads(result.stdout)["vpn_node_credentials"]
            self.assertEqual(set(data), set(prepare.credentials()))
            with patch.object(prepare, "credentials") as generate:
                with self.assertRaises(FileExistsError):
                    prepare.prepare(output, password)
                generate.assert_not_called()
            self.assertEqual(output.read_bytes(), before)

    def test_refuses_symlinks_including_dangling_links(self):
        with tempfile.TemporaryDirectory() as work:
            directory = Path(work)
            link = directory / "vault"
            link.symlink_to(directory / "missing")
            with self.assertRaises(FileExistsError):
                prepare.prepare(link, directory / "password")
            self.assertTrue(link.is_symlink())
            self.assertFalse(link.exists())


if __name__ == "__main__":
    unittest.main()
