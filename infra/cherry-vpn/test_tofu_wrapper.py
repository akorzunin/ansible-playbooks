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
            "print(json.dumps({'digest': hashlib.sha256(key.encode()).hexdigest(), 'args': sys.argv[1:]}))\n"
        )
        executable.chmod(0o700)
        self.env = {key: value for key, value in os.environ.items() if key != "CHERRY_API_KEY"}

    def encrypt(self, value):
        subprocess.run(
            ["ansible-vault", "encrypt", "--vault-password-file", str(self.password),
             "--output", str(self.vault)],
            input=value, text=True, capture_output=True, check=True,
        )

    def invoke(self, trace=False):
        return subprocess.run(
            ["bash", *(["-x"] if trace else []), str(self.project / "tofu.sh"), "validate"],
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

    def test_no_vault_allows_offline_commands_without_a_token(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["digest"], hashlib.sha256(b"").hexdigest())


if __name__ == "__main__":
    unittest.main()
