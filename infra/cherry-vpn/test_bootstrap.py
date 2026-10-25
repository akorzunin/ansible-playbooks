"""Local-only Vault/encryption recovery tests. No Cherry API calls or billable resources."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("bootstrap_credentials", ROOT / "prepare-bootstrap.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


@unittest.skipUnless(shutil.which("ansible-vault") and shutil.which("ssh-keygen"), "Vault and OpenSSH required")
class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = self.root / "infra/cherry-vpn"
        self.project.mkdir(parents=True)
        self.password = self.root / ".ansible_pass"
        self.password.write_text("bootstrap-test-vault-password\n")
        self.vault = self.project / "secrets.vault.yaml"
        bootstrap.write_vault(self.vault, self.password, {"vpn_node_credentials": {"sentinel": "preserve-existing"}})

    def test_preparation_and_rotation_preserve_encryption_secret_and_proxy_credentials(self):
        first, changed = bootstrap.prepare(self.vault, self.password)
        self.assertTrue(changed)
        before = self.vault.read_bytes()
        again, changed = bootstrap.prepare(self.vault, self.password)
        self.assertFalse(changed)
        self.assertEqual(first, again)
        self.assertEqual(before, self.vault.read_bytes())
        rotated, changed = bootstrap.prepare(self.vault, self.password, rotate=True)
        self.assertTrue(changed)
        self.assertEqual(first["state_passphrase"], rotated["state_passphrase"])
        self.assertNotEqual(first["ssh_host_key"], rotated["ssh_host_key"])
        restored = bootstrap.read_vault(self.vault, self.password)
        self.assertEqual(restored["vpn_node_credentials"], {"sentinel": "preserve-existing"})
        self.assertEqual(restored["vpn_bootstrap"], rotated)
        self.assertTrue(self.vault.read_bytes().startswith(b"$ANSIBLE_VAULT;"))
        self.assertEqual(self.vault.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(rotated["ssh_host_key"]["private"].encode(), self.vault.read_bytes())
        self.assertEqual(list(self.project.iterdir()), [self.vault])
        key = self.root / "fixture-key"
        key.write_text(rotated["ssh_host_key"]["private"])
        key.chmod(0o600)
        public = subprocess.run(["ssh-keygen", "-y", "-f", str(key)], check=True, capture_output=True, text=True).stdout
        self.assertEqual(public.split()[:2], rotated["ssh_host_key"]["public"].split()[:2])

    def test_invalid_existing_bootstrap_is_not_silently_regenerated(self):
        bootstrap.write_vault(self.vault, self.password, {"vpn_bootstrap": {"state_passphrase": "short"}})
        before = self.vault.read_bytes()
        with self.assertRaises(ValueError):
            bootstrap.prepare(self.vault, self.password)
        self.assertEqual(before, self.vault.read_bytes())

    def test_migration_refuses_remote_backends_workspaces_and_incomplete_recovery(self):
        spec = importlib.util.spec_from_file_location("tofu_wrapper", ROOT / "tofu.py")
        wrapper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wrapper)
        state = self.project / "terraform.tfstate"
        state.write_text('{"version": 4, "resources": []}')
        original = state.read_bytes()
        metadata = self.project / ".terraform/terraform.tfstate"
        metadata.parent.mkdir()
        metadata.write_text('{"backend": {"type": "s3"}}')
        with patch.object(wrapper, "ROOT", self.project):
            with self.assertRaises(ValueError):
                wrapper.migrate("must-not-run", {})
            metadata.unlink()
            with self.assertRaises(ValueError):
                wrapper.migrate("must-not-run", {"TF_WORKSPACE": "another-state"})
            with self.assertRaises(ValueError):
                wrapper.migrate("must-not-run", {"TF_DATA_DIR": "/another-backend"})
            pending = self.project / "private/migration-original.tfstate"
            pending.parent.mkdir()
            pending.write_text("recovery-fixture")
            with self.assertRaises(ValueError):
                wrapper.migrate("must-not-run", {})
        self.assertEqual(state.read_bytes(), original)
        self.assertEqual(pending.read_text(), "recovery-fixture")

    @unittest.skipUnless((ROOT / ".tools/tofu").exists() or shutil.which("tofu"), "OpenTofu required")
    def test_real_state_migration_plan_encryption_wrong_key_and_plaintext_rejection(self):
        data, _ = bootstrap.prepare(self.vault, self.password)
        executable = (ROOT / ".tools/tofu").resolve() if (ROOT / ".tools/tofu").exists() else Path(shutil.which("tofu"))
        tools = self.project / ".tools"
        tools.mkdir()
        (tools / "tofu").symlink_to(executable)
        for name in ("tofu.sh", "tofu.py", "prepare-bootstrap.py"):
            shutil.copyfile(ROOT / name, self.project / name)
        variables = '''
variable "state_encryption_passphrase" { type = string }
variable "ssh_host_key" { type = object({ private = string, public = string }) }
'''
        config = self.project / "main.tf"
        config.write_text(variables + '\noutput "legacy" { value = "before-encryption" }\n')
        environment = {key: value for key, value in os.environ.items()
                       if key not in {"TF_ENCRYPTION", "TF_LOG", "TF_LOG_CORE", "TF_LOG_PROVIDER"}}
        environment["TF_VAR_state_encryption_passphrase"] = data["state_passphrase"]
        environment["TF_VAR_ssh_host_key"] = json.dumps(data["ssh_host_key"])

        def raw(*args, env=None):
            return subprocess.run([str(executable), *args], cwd=self.project, env=env or environment,
                                  capture_output=True, text=True, timeout=60)

        def wrapped(*args):
            result = subprocess.run(["bash", str(self.project / "tofu.sh"), *args], cwd=self.project,
                                    env=environment, capture_output=True, text=True, timeout=60)
            self.assertNotIn(data["ssh_host_key"]["private"], result.stdout + result.stderr)
            self.assertNotIn(data["state_passphrase"], result.stdout + result.stderr)
            return result

        self.assertEqual(raw("init", "-backend=false").returncode, 0)
        result = raw("apply", "-input=false", "-auto-approve")
        self.assertEqual(result.returncode, 0, result.stderr)
        state_path = self.project / "terraform.tfstate"
        legacy_state = state_path.read_bytes()
        production = (ROOT / "main.tf").read_text()
        encryption_block = production[production.index("  encryption {"):production.index("\n  required_providers")]
        config.write_text(variables + "\nterraform {\n" + encryption_block + "\n}\n" + '''
output "secret_fixture" {
  value = sensitive(var.ssh_host_key.private)
  sensitive = true
}
''')
        # Enforced encryption refuses plaintext before the explicit migration.
        self.assertNotEqual(wrapped("state", "list").returncode, 0)
        result = wrapped("migrate-state")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        cipher_state = state_path.read_bytes()
        self.assertIn("encryption_version", json.loads(cipher_state))
        self.assertNotIn(b"BEGIN OPENSSH PRIVATE KEY", cipher_state)
        self.assertNotIn(data["state_passphrase"].encode(), cipher_state)
        backup = self.project / "private/pre-encryption-terraform.tfstate.vault"
        restored = subprocess.run(["ansible-vault", "view", "--vault-password-file", str(self.password), str(backup)],
                                  check=True, capture_output=True).stdout
        self.assertEqual(restored, legacy_state)
        self.assertFalse((self.project / "terraform.tfstate.backup").exists())
        # Idempotent migration must not rotate the key or downgrade encryption.
        result = wrapped("migrate-state")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = wrapped("plan", "-input=false", "-out=private/check.tfplan")
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = self.project / "private/check.tfplan"
        self.assertNotIn(b"BEGIN OPENSSH PRIVATE KEY", plan.read_bytes())
        self.assertIn("encryption_version", json.loads(plan.read_bytes()))
        shown = raw("show", "-json", str(plan))
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertEqual(json.loads(shown.stdout)["variables"]["ssh_host_key"]["value"], data["ssh_host_key"])
        wrong_key = {**environment, "TF_VAR_state_encryption_passphrase": "wrong-test-key-which-is-long-enough"}
        self.assertNotEqual(raw("state", "list", env=wrong_key).returncode, 0)
        state_path.write_bytes(legacy_state)
        self.assertNotEqual(wrapped("state", "list").returncode, 0)
        state_path.write_bytes(cipher_state)
        result = wrapped("state", "list")
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
