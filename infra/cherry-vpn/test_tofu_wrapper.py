import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

WRAPPER = Path(__file__).with_name("tofu.sh")
TOKEN = "synthetic-test-token-not-a-real-credential"


@unittest.skipUnless(shutil.which("ansible-vault"), "ansible-vault is required")
class VaultWrapperTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = self.root / "infra" / "cherry-vpn"
        self.project.mkdir(parents=True)
        shutil.copyfile(WRAPPER, self.project / "tofu.sh")
        for name in ("tofu.py", "prepare-bootstrap.py"):
            shutil.copyfile(WRAPPER.with_name(name), self.project / name)
        self.password = self.root / ".ansible_pass"
        self.password.write_text("synthetic-vault-password\n")
        self.password.chmod(0o600)
        self.vault = self.project / "cherry-token.vault"
        tools = self.project / ".tools"
        tools.mkdir()
        executable = tools / "tofu"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import hashlib, json, os, sys\n"
            "key = os.environ.get('CHERRY_API_KEY', '')\n"
            "data = {'digest': hashlib.sha256(key.encode()).hexdigest(), 'args': sys.argv[1:]}\n"
            "if os.environ.get('TEST_BOOTSTRAP_DIGESTS'):\n"
            "    data['state_digest'] = hashlib.sha256(os.environ.get('TF_VAR_state_encryption_passphrase', '').encode()).hexdigest()\n"
            "    data['host_digest'] = hashlib.sha256(os.environ.get('TF_VAR_ssh_host_key', '').encode()).hexdigest()\n"
            "if sys.argv[1:] == ['show', '-json'] and os.environ.get('TEST_APPLIED_STATE'):\n"
            "    print(os.environ['TEST_APPLIED_STATE'])\n"
            "else:\n"
            "    print(json.dumps(data))\n"
        )
        executable.chmod(0o700)
        self.env = {key: value for key, value in os.environ.items() if key != "CHERRY_API_KEY"}

    def encrypt(self, value):
        subprocess.run(
            ["ansible-vault", "encrypt", "--vault-password-file", str(self.password),
             "--output", str(self.vault)],
            input=value, text=True, capture_output=True, check=True,
        )

    def invoke(self, trace=False, args=None):
        return subprocess.run(
            ["bash", *(["-x"] if trace else []), str(self.project / "tofu.sh"), *(args or ["validate"])],
            cwd=self.root, env=self.env, capture_output=True, text=True,
        )

    def test_decrypts_into_child_environment_without_disclosing_token(self):
        self.encrypt(TOKEN + "\n")
        result = self.invoke(trace=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            "digest": hashlib.sha256(TOKEN.encode()).hexdigest(), "args": ["validate"],
        })
        self.assertNotIn(TOKEN, result.stdout + result.stderr)
        self.assertTrue(self.vault.read_text().startswith("$ANSIBLE_VAULT;"))

    def test_environment_override_does_not_require_decrypting_vault(self):
        self.vault.write_text("deliberately invalid vault")
        self.env["CHERRY_API_KEY"] = TOKEN
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["digest"], hashlib.sha256(TOKEN.encode()).hexdigest())

    def test_wrong_password_stops_before_tofu(self):
        self.encrypt(TOKEN)
        self.password.write_text("wrong-password\n")
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertNotIn(TOKEN, result.stderr)

    def test_empty_or_structured_secret_stops_before_tofu(self):
        for content in ("\n", "CHERRY_API_KEY: token\n", "first-token\nsecond-token\n"):
            with self.subTest(content=content):
                self.vault.unlink(missing_ok=True)
                self.encrypt(content)
                result = self.invoke()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertNotIn(content.strip() or "unused-sentinel", result.stderr)

    def test_plaintext_vault_file_is_not_accepted(self):
        self.vault.write_text(TOKEN)
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertNotIn(TOKEN, result.stderr)

    def encrypt_bootstrap(self):
        data = {
            "state_passphrase": "synthetic-test-state-encryption-passphrase",
            "ssh_host_key": {
                "private": "-----BEGIN OPENSSH PRIVATE KEY-----\\nsynthetic-private-fixture",
                "public": WRAPPER.with_name("tests").joinpath("admin.pub").read_text().strip(),
            },
        }
        subprocess.run(
            ["ansible-vault", "encrypt", "--vault-password-file", str(self.password),
             "--output", str(self.project / "secrets.vault.yaml")],
            input=json.dumps({"vpn_bootstrap": data}), text=True, capture_output=True, check=True,
        )
        return data

    def test_stateful_commands_require_bootstrap_and_reject_encryption_debug_overrides(self):
        result = self.invoke(args=["plan"])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.encrypt_bootstrap()
        for key in ("TF_ENCRYPTION", "TF_LOG", "TF_LOG_CORE", "TF_LOG_PROVIDER"):
            self.env[key] = "unsafe-override"
            result = self.invoke(args=["plan"])
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            del self.env[key]

    def test_stateful_secrets_come_from_vault_environment_not_arguments_or_inherited_inputs(self):
        data = self.encrypt_bootstrap()
        self.env.update({"TEST_BOOTSTRAP_DIGESTS": "1", "TF_VAR_state_encryption_passphrase": "wrong-inherited-key",
                         "TF_VAR_ssh_host_key": "wrong-inherited-host"})
        result = self.invoke(trace=True, args=["plan"])
        self.assertEqual(result.returncode, 0, result.stderr)
        child = json.loads(result.stdout)
        self.assertEqual(child["args"], ["plan"])
        self.assertEqual(child["state_digest"], hashlib.sha256(data["state_passphrase"].encode()).hexdigest())
        self.assertEqual(child["host_digest"], hashlib.sha256(json.dumps(data["ssh_host_key"]).encode()).hexdigest())
        self.assertNotIn(data["state_passphrase"], result.stdout + result.stderr)
        self.assertNotIn(data["ssh_host_key"]["private"], result.stdout + result.stderr)

    def test_inventory_pins_only_the_applied_host_identity_and_rejects_pending_rotation(self):
        data = self.encrypt_bootstrap()
        cloud = {"ssh_keys": {"ed25519_public": data["ssh_host_key"]["public"]}}
        server = {"id": "123", "user_data": base64.b64encode(("#cloud-config\n" + json.dumps(cloud)).encode()).decode(),
                  "ip_addresses": [{"type": "primary-ip", "address_family": 4, "address": "8.8.8.8"}]}
        state = {"values": {"root_module": {"resources": [{"address": "cherryservers_server.vpn", "values": server}]}}}
        self.env["TEST_APPLIED_STATE"] = json.dumps(state)
        result = self.invoke(args=["inventory", "--proxy-command", "nc -X connect -x 127.0.0.1:12334 %h %p"])
        self.assertEqual(result.returncode, 0, result.stderr)
        known = self.project / "private/known_hosts"
        before = known.read_bytes()
        self.assertIn(data["ssh_host_key"]["public"], before.decode())
        self.assertEqual(known.stat().st_mode & 0o777, 0o600)
        inventory = json.loads((self.project / "private/inventory.yaml").read_text())
        host = inventory["all"]["children"]["vpn_test"]["hosts"]["cherry_vpn_test"]
        self.assertEqual(host["cherry_server_id"], "123")
        self.assertIn("StrictHostKeyChecking=yes", host["ansible_ssh_common_args"])
        self.assertIn("ProxyCommand=nc", host["ansible_ssh_common_args"])
        self.assertIn("ServerAliveInterval=15", host["ansible_ssh_common_args"])
        result = self.invoke(args=["inventory"])
        self.assertEqual(result.returncode, 0, result.stderr)
        retained = json.loads((self.project / "private/inventory.yaml").read_text())
        self.assertIn("ProxyCommand=nc", retained["all"]["children"]["vpn_test"]["hosts"]["cherry_vpn_test"]["ansible_ssh_common_args"])
        self.assertNotIn(data["ssh_host_key"]["private"], result.stdout + result.stderr)
        cloud["ssh_keys"]["ed25519_public"] = "ssh-ed25519 AAAA-different-pending-host"
        server["user_data"] = base64.b64encode(("#cloud-config\n" + json.dumps(cloud)).encode()).decode()
        self.env["TEST_APPLIED_STATE"] = json.dumps(state)
        result = self.invoke(args=["inventory"])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(known.read_bytes(), before)

    def test_no_vault_allows_offline_commands_without_a_token(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["digest"], hashlib.sha256(b"").hexdigest())


if __name__ == "__main__":
    unittest.main()
