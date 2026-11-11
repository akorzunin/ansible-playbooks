"""Secret insertion must preserve unrelated YAML and shared-file symlinks."""

import importlib.util
import io
import os
from pathlib import Path
import pty
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml


SCRIPT = Path(__file__).resolve().parents[1] / "encrypt-var.py"
SPEC = importlib.util.spec_from_file_location("encrypt_var", SCRIPT)
encrypt_var = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(encrypt_var)
BLOCK = "TOKEN: !vault |\n  encrypted-fixture\n"


class UpdateVariableTests(unittest.TestCase):
    def test_append_before_document_end_preserves_comments_and_ciphertext(self):
        original = "---\n# keep\nOTHER: !vault |\n  old-ciphertext\n# trailing\n...\n"
        result = encrypt_var.update_variable(original, "TOKEN", BLOCK)
        self.assertEqual(result, original.replace("...\n", BLOCK + "...\n"))

    def test_replace_plain_or_encrypted_scalar_without_duplicate_keys(self):
        for previous in ('TOKEN: "old" # replaced comment\n',
                         'TOKEN: !vault |\n  old-ciphertext\n',
                         'TOKEN: old', 'TOKEN:\n', 'TOKEN: |\n  multiple\n  lines\n'):
            with self.subTest(previous=previous):
                original = "# keep\nOTHER: unchanged\n" + previous
                result = encrypt_var.update_variable(original, "TOKEN", BLOCK)
                self.assertEqual(result, "# keep\nOTHER: unchanged\n" + BLOCK)

    def test_replace_preserves_following_entries_and_comments(self):
        original = "TOKEN: old\n# keep\nOTHER: unchanged\n"
        self.assertEqual(encrypt_var.update_variable(original, "TOKEN", BLOCK),
                         BLOCK + "# keep\nOTHER: unchanged\n")

    def test_append_without_final_newline(self):
        self.assertEqual(encrypt_var.update_variable("OTHER: old", "TOKEN", BLOCK),
                         "OTHER: old\n" + BLOCK)

    def test_reject_ambiguous_or_non_scalar_updates(self):
        for original in ("TOKEN: one\nTOKEN: two\n", "{TOKEN: old}\n", "- old\n", "",
                         "TOKEN:\n  nested: old\n", "TOKEN: [one, two]\n",
                         "OTHER: &old secret\nTOKEN: *old\n",
                         "TOKEN: &old secret\nOTHER: *old\n", "? TOKEN\n: old\n"):
            with self.subTest(original=original):
                with self.assertRaises((ValueError, yaml.YAMLError)):
                    encrypt_var.update_variable(original, "TOKEN", BLOCK)

    def test_invalid_yaml_is_rejected_before_opening_editor(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "external_vars.yml"
            original = "TOKEN: !vault |\n$ANSIBLE_VAULT;1.1;AES256\n616263\n"
            target.write_text(original)
            with patch.object(encrypt_var.subprocess, "run") as run:
                with self.assertRaises(yaml.YAMLError):
                    encrypt_var.save_variable(target, Path(directory) / "password", "TOKEN")
                run.assert_not_called()
            self.assertEqual(target.read_text(), original)

    def test_yaml_error_reports_location_without_source_snippet(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "external_vars.yml"
            target.write_text("TOKEN: !vault |\nsensitive-plaintext\ninvalid\n")
            with patch.object(sys, "argv", [str(SCRIPT), "--vars-file", str(target)]), \
                 patch("builtins.input", return_value="TOKEN"), \
                 patch("sys.stderr", new_callable=io.StringIO) as stderr:
                with self.assertRaises(SystemExit) as exited:
                    encrypt_var.main()
                self.assertEqual(exited.exception.code, 1)
                self.assertIn(str(target), stderr.getvalue())
                self.assertIn("line 3, column 1", stderr.getvalue())
                self.assertNotIn("sensitive-plaintext", stderr.getvalue())

    def test_encryption_failure_leaves_file_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "external_vars.yml"
            target.write_text("OTHER: unchanged\n")
            with patch.object(encrypt_var.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "vault")):
                with self.assertRaises(subprocess.CalledProcessError):
                    encrypt_var.save_variable(target, Path(directory) / "password", "TOKEN")
            self.assertEqual(target.read_text(), "OTHER: unchanged\n")
            self.assertEqual(list(Path(directory).iterdir()), [target])

    @unittest.skipUnless(shutil.which("ansible-vault"), "Ansible Vault required")
    def test_real_encryption_round_trip_preserves_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "shared.yml"
            target.write_text("# keep\nOTHER: unchanged\nTOKEN: old\n")
            link = root / "external_vars.yml"
            link.symlink_to(target)
            password = root / "password"
            password.write_text("synthetic-vault-password\n")
            secret = "synthetic secret: 'quotes' \\ slash\nsecond line with trailing spaces  \n"
            editor = root / "editor.py"
            editor.write_text("import pathlib, sys\npathlib.Path(sys.argv[1]).write_text(" + repr(secret) + ")\n")
            master, slave = pty.openpty()
            run = subprocess.run
            with os.fdopen(master, "rb"), os.fdopen(slave, "wb") as terminal:
                with patch.dict(os.environ, {"EDITOR": f"{sys.executable} {editor}"}), \
                     patch.object(encrypt_var.subprocess, "run",
                                  side_effect=lambda *args, **kwargs: run(*args, stdout=terminal, **kwargs)):
                    encrypt_var.save_variable(link, password, "TOKEN")
            self.assertTrue(link.is_symlink())
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertNotIn(secret, target.read_text())
            self.assertTrue(target.read_text().startswith("# keep\nOTHER: unchanged\nTOKEN: !vault |\n"))
            node = yaml.compose(target.read_text(), Loader=yaml.BaseLoader)
            ciphertext = dict((key.value, value.value) for key, value in node.value)["TOKEN"]
            result = subprocess.run(
                ["ansible-vault", "decrypt", "--vault-password-file", str(password), "--output", "-"],
                input=ciphertext, text=True, capture_output=True, check=True,
            )
            self.assertEqual(result.stdout, secret)
            self.assertEqual({path.name for path in root.iterdir()},
                             {"shared.yml", "external_vars.yml", "password", "editor.py"})


if __name__ == "__main__":
    unittest.main()
