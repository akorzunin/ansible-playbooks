"""Exercise Dropbox linking without touching real controller files."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


INSTALLER = Path(__file__).resolve().parents[1] / "install.sh"


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "checkout"
        self.cherry = self.repo / "infra/cherry-vpn"
        self.cherry.mkdir(parents=True)
        shutil.copyfile(INSTALLER, self.repo / "install.sh")
        self.home = self.root / "home"
        self.dropbox = self.home / "Dropbox/ssh"
        self.dropbox.mkdir(parents=True)
        for name in ("hosts", "external_vars.yml"):
            (self.dropbox / name).write_text("private fixture\n")
        self.env = {**os.environ, "HOME": str(self.home)}
        self.env.pop("DROPBOX_SSH_DIR", None)

    def run_install(self):
        return subprocess.run(
            ["bash", str(self.repo / "install.sh")], cwd=self.root,
            env=self.env, capture_output=True, text=True,
        )

    def shared_cherry(self):
        directory = self.dropbox / "cherry-vpn"
        directory.mkdir()
        for name in ("cherry-token.vault", "terraform.tfvars"):
            (directory / name).write_text("private fixture\n")
        return directory

    def test_links_all_inputs_and_is_idempotent(self):
        shared = self.shared_cherry()
        for _ in range(2):
            result = self.run_install()
            self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("hosts", "external_vars.yml"):
            self.assertEqual((self.repo / name).readlink(), self.dropbox / name)
        for name in ("cherry-token.vault", "terraform.tfvars"):
            self.assertEqual((self.cherry / name).readlink(), shared / name)

    def test_ansible_only_install(self):
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Skipping OpenTofu links", result.stdout)
        self.assertFalse((self.cherry / "terraform.tfvars").exists())

    def test_relative_override_with_spaces(self):
        self.shared_cherry()
        directory = self.root / "custom Dropbox"
        self.dropbox.rename(directory)
        self.dropbox = directory
        self.env["DROPBOX_SSH_DIR"] = directory.name
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.cherry / "terraform.tfvars").readlink(), directory / "cherry-vpn/terraform.tfvars")
        self.assertTrue((self.repo / "hosts").is_file())

    def test_termux_fallback(self):
        directory = self.home / "storage/shared/Dropbox/ssh"
        directory.parent.mkdir(parents=True)
        self.dropbox.rename(directory)
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.repo / "hosts").readlink(), directory / "hosts")

    def test_missing_dropbox(self):
        shutil.rmtree(self.dropbox)
        result = self.run_install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Set DROPBOX_SSH_DIR", result.stderr)

    def test_missing_required_file(self):
        (self.dropbox / "hosts").unlink()
        result = self.run_install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing Dropbox file", result.stderr)

    def test_incomplete_cherry_directory_fails(self):
        shared = self.shared_cherry()
        (shared / "cherry-token.vault").unlink()
        result = self.run_install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(shared / "cherry-token.vault"), result.stderr)

    def test_refuses_existing_file_or_symlink(self):
        self.shared_cherry()
        target = self.cherry / "terraform.tfvars"
        for kind in ("file", "symlink", "broken symlink"):
            with self.subTest(kind=kind):
                if kind == "file":
                    target.write_text("keep me\n")
                elif kind == "symlink":
                    target.symlink_to(self.dropbox / "hosts")
                else:
                    target.symlink_to(self.root / "missing")
                result = self.run_install()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Refusing to replace existing path", result.stderr)
                if kind == "file":
                    self.assertEqual(target.read_text(), "keep me\n")
                else:
                    self.assertTrue(target.is_symlink())
                target.unlink()

    def test_state_password_and_working_files_stay_local(self):
        shared = self.shared_cherry()
        paths = ("terraform.tfstate", "terraform.tfstate.backup", "private/ssh/admin", "project.auto.tfvars.json")
        for name in paths:
            target = self.cherry / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("local fixture\n")
            source = shared / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("do not link\n")
        password = self.repo / ".ansible_pass"
        password.write_text("local fixture\n")
        (self.dropbox / ".ansible_pass").write_text("do not link\n")
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        for target in (password, *(self.cherry / name for name in paths)):
            self.assertFalse(target.is_symlink())
            self.assertEqual(target.read_text(), "local fixture\n")


if __name__ == "__main__":
    unittest.main()
