"""Exercise Dropbox linking without touching real controller files."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


INSTALLER = Path(__file__).resolve().parents[1] / "install.sh"
OPTIONAL_INPUTS = (
    "playbooks/3proxy/users.env",
    "playbooks/duckdns-ui/.env",
    "playbooks/firefly/.env",
    "playbooks/firefly/.db.env",
    "playbooks/firefly/.importer.env",
    "playbooks/wake-on-lan/computers.txt",
)


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

    def run_install(self, *args):
        return subprocess.run(
            ["bash", str(self.repo / "install.sh"), *args], cwd=self.root,
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

    def test_restores_optional_inputs_in_fresh_checkout(self):
        for name in OPTIONAL_INPUTS:
            source = self.dropbox / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("shared fixture\n")
        for _ in range(2):
            result = self.run_install()
            self.assertEqual(result.returncode, 0, result.stderr)
        for name in OPTIONAL_INPUTS:
            self.assertEqual((self.repo / name).readlink(), self.dropbox / name)

    def test_migrates_local_inputs_then_restores_on_another_controller(self):
        names = ("hosts", "external_vars.yml", *OPTIONAL_INPUTS,
                 "infra/cherry-vpn/cherry-token.vault", "infra/cherry-vpn/terraform.tfvars")
        for name in ("hosts", "external_vars.yml"):
            (self.dropbox / name).unlink()
        for name in names:
            target = self.repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("local fixture\n")
        result = self.run_install("--migrate")
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in names:
            shared = name.removeprefix("infra/")
            source = self.dropbox / shared
            self.assertEqual((self.repo / name).readlink(), source)
            self.assertEqual(source.read_text(), "local fixture\n")
            self.assertEqual(source.stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.dropbox / "playbooks/firefly").stat().st_mode & 0o777, 0o700)

        self.repo = self.root / "second checkout"
        self.repo.mkdir()
        shutil.copyfile(INSTALLER, self.repo / "install.sh")
        for _ in range(2):
            result = self.run_install()
            self.assertEqual(result.returncode, 0, result.stderr)
        for name in names:
            self.assertEqual((self.repo / name).read_text(), "local fixture\n")
            self.assertTrue((self.repo / name).is_symlink())

    def test_local_optional_input_requires_explicit_migration(self):
        target = self.repo / "playbooks/3proxy/users.env"
        target.parent.mkdir(parents=True)
        target.write_text("keep me\n")
        result = self.run_install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--migrate", result.stderr)
        self.assertEqual(target.read_text(), "keep me\n")
        self.assertFalse((self.repo / "hosts").exists())

    def test_migration_adopts_identical_shared_file(self):
        target = self.repo / "hosts"
        target.write_bytes((self.dropbox / "hosts").read_bytes())
        result = self.run_install("--migrate")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(target.readlink(), self.dropbox / "hosts")

    def test_conflict_aborts_before_any_links_or_moves(self):
        target = self.repo / "external_vars.yml"
        target.write_text("local fixture\n")
        source = self.dropbox / "external_vars.yml"
        source.write_text("different shared fixture\n")
        result = self.run_install("--migrate")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Conflicting", result.stderr)
        self.assertFalse((self.repo / "hosts").exists())
        self.assertEqual(target.read_text(), "local fixture\n")
        self.assertEqual(source.read_text(), "different shared fixture\n")

    def test_migration_refuses_wrong_or_broken_local_symlink(self):
        for destination in (self.dropbox / "hosts", self.root / "missing"):
            with self.subTest(destination=destination):
                target = self.repo / "external_vars.yml"
                target.symlink_to(destination)
                result = self.run_install("--migrate")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Refusing", result.stderr)
                self.assertEqual(target.readlink(), destination)
                target.unlink()

    def test_dropbox_input_cannot_be_a_symlink(self):
        source = self.dropbox / "external_vars.yml"
        source.unlink()
        source.symlink_to(self.dropbox / "hosts")
        result = self.run_install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("regular file", result.stderr)
        self.assertFalse((self.repo / "hosts").exists())

    def test_migration_cannot_delete_input_when_dropbox_is_checkout(self):
        for name in ("hosts", "external_vars.yml"):
            (self.repo / name).write_text("keep me\n")
        self.env["DROPBOX_SSH_DIR"] = str(self.repo)
        result = self.run_install("--migrate")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("separate files", result.stderr)
        self.assertEqual((self.repo / "hosts").read_text(), "keep me\n")

    def test_invalid_arguments(self):
        for args in (("--unknown",), ("--migrate", "extra")):
            with self.subTest(args=args):
                result = self.run_install(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Usage:", result.stderr)

    def test_legacy_monitoring_inputs_are_not_synced(self):
        for name in ("monitoring.inventory.yml", "playbooks/ws-logs/.env"):
            target = self.repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("obsolete local fixture\n")
        result = self.run_install("--migrate")
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("monitoring.inventory.yml", "playbooks/ws-logs/.env"):
            self.assertFalse((self.repo / name).is_symlink())
            self.assertFalse((self.dropbox / name).exists())

    def test_state_password_and_working_files_stay_local(self):
        shared = self.shared_cherry()
        paths = ("terraform.tfstate", "terraform.tfstate.backup", "private/ssh/admin", "project.auto.tfvars.json", ".terraform/provider", ".tools/tofu")
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
        generated = self.repo / "playbooks/sing-box-configs/private/tokens.json"
        generated.parent.mkdir(parents=True)
        generated.write_text("local fixture\n")
        for args in ((), ("--migrate",)):
            result = self.run_install(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
            for target in (password, generated, *(self.cherry / name for name in paths)):
                self.assertFalse(target.is_symlink())
                self.assertEqual(target.read_text(), "local fixture\n")


if __name__ == "__main__":
    unittest.main()
