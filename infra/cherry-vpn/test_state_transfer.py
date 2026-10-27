"""Encrypted Dropbox snapshots only; no provider or cloud API calls."""
import fcntl
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
spec = importlib.util.spec_from_file_location("state_transfer_wrapper", ROOT / "tofu.py")
wrapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wrapper)


def ciphertext(value):
    return json.dumps({"encryption_version": "v0", "encrypted_data": value})


class StateTransferTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = self.root / "checkout/infra/cherry-vpn"
        self.project.mkdir(parents=True)
        self.dropbox = self.root / "Dropbox/ssh"
        self.shared = self.dropbox / "cherry-vpn"
        self.shared.mkdir(parents=True)
        self.env = {"DROPBOX_SSH_DIR": str(self.dropbox)}
        self.state = self.project / "terraform.tfstate"
        self.backup = self.project / "terraform.tfstate.backup"
        self.state.write_text(ciphertext("current"))
        self.backup.write_text(ciphertext("previous"))
        self.patch = patch.object(wrapper, "ROOT", self.project)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def transfer(self, command):
        return wrapper.transfer_state(command, self.env)

    def test_backup_and_restore_are_exact_private_and_idempotent(self):
        originals = {path.name: path.read_bytes() for path in (self.state, self.backup)}
        self.transfer("backup-state")
        self.transfer("backup-state")
        for name, content in originals.items():
            shared = self.shared / name
            self.assertEqual(shared.read_bytes(), content)
            self.assertEqual(shared.stat().st_mode & 0o777, 0o600)
            (self.project / name).unlink()
        self.transfer("restore-state")
        self.transfer("restore-state")
        for name, content in originals.items():
            local = self.project / name
            self.assertEqual(local.read_bytes(), content)
            self.assertEqual(local.stat().st_mode & 0o777, 0o600)
            self.assertFalse(local.is_symlink())
        self.assertEqual(sorted(path.name for path in self.shared.iterdir()), sorted(originals))

    def test_backup_updates_snapshot_after_local_changes(self):
        self.transfer("backup-state")
        self.backup.write_bytes(self.state.read_bytes())
        self.state.write_text(ciphertext("next"))
        self.transfer("backup-state")
        self.assertEqual((self.shared / self.state.name).read_bytes(), self.state.read_bytes())
        self.assertEqual((self.shared / self.backup.name).read_bytes(), self.backup.read_bytes())

    def test_restore_never_overwrites_different_local_state(self):
        self.transfer("backup-state")
        self.state.write_text(ciphertext("different"))
        self.backup.unlink()
        with self.assertRaisesRegex(ValueError, "Different local state"):
            self.transfer("restore-state")
        self.assertEqual(self.state.read_text(), ciphertext("different"))
        self.assertFalse(self.backup.exists())

    def test_plaintext_state_or_backup_is_rejected_before_any_copy(self):
        for command in ("backup-state", "restore-state"):
            source = self.project if command == "backup-state" else self.shared
            target = self.shared if command == "backup-state" else self.project
            for bad_name in (self.state.name, self.backup.name):
                with self.subTest(command=command, bad_name=bad_name):
                    for name in (self.state.name, self.backup.name):
                        (target / name).unlink(missing_ok=True)
                        (source / name).write_text(ciphertext("fixture"))
                    (source / bad_name).write_text('{"version": 4, "resources": []}')
                    with self.assertRaisesRegex(ValueError, "Only encrypted"):
                        self.transfer(command)
                    self.assertEqual(list(target.iterdir()), [])

    def test_malformed_or_mixed_plaintext_envelopes_are_rejected(self):
        invalid = ("not json", "[]", "{}", ciphertext(""),
                   '{"encryption_version": "v0", "encrypted_data": "fixture", "resources": []}')
        for content in invalid:
            with self.subTest(content=content):
                self.state.write_text(content)
                with self.assertRaises(ValueError):
                    self.transfer("backup-state")
                self.assertEqual(list(self.shared.iterdir()), [])

    def test_symlink_sources_and_destinations_are_rejected(self):
        for directory in (self.project, self.shared):
            with self.subTest(directory=directory):
                path = directory / self.state.name
                path.unlink(missing_ok=True)
                path.symlink_to(self.root / "missing")
                with self.assertRaisesRegex(ValueError, "not symlinks"):
                    self.transfer("backup-state")
                path.unlink()
                self.state.write_text(ciphertext("current"))
        self.assertEqual(list(self.shared.iterdir()), [])

    def test_missing_main_state_cannot_copy_backup_only(self):
        self.state.unlink()
        with self.assertRaises(FileNotFoundError):
            self.transfer("backup-state")
        self.assertEqual(list(self.shared.iterdir()), [])

    def test_backup_is_optional(self):
        self.backup.unlink()
        self.transfer("backup-state")
        self.assertEqual([path.name for path in self.shared.iterdir()], [self.state.name])

    def test_missing_dropbox_is_not_created(self):
        self.env["DROPBOX_SSH_DIR"] = str(self.root / "missing")
        with self.assertRaisesRegex(ValueError, "directory not found"):
            self.transfer("backup-state")
        self.assertFalse((self.root / "missing").exists())

    def test_default_and_termux_discovery(self):
        self.env.clear()
        for directory in (self.root / "Dropbox/ssh", self.root / "storage/shared/Dropbox/ssh"):
            with self.subTest(directory=directory), patch.object(Path, "home", return_value=self.root):
                if directory != self.dropbox:
                    directory.parent.mkdir(parents=True)
                    self.dropbox.rename(directory)
                self.assertEqual(self.transfer("backup-state"), 0)
                self.assertTrue((directory / "cherry-vpn/terraform.tfstate").is_file())

    def test_nondefault_paths_workspaces_and_backends_are_rejected(self):
        for key, value in (("TF_WORKSPACE", "other"), ("TF_DATA_DIR", "/elsewhere"),
                           ("TF_CLI_ARGS", "-state=other"), ("TF_CLI_ARGS_apply", "-state=other")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                wrapper.transfer_state("backup-state", {**self.env, key: value})
        metadata = self.project / ".terraform/terraform.tfstate"
        metadata.parent.mkdir()
        for backend in ({"type": "s3"}, {"type": "local", "config": {"path": "other.tfstate"}}):
            metadata.write_text(json.dumps({"backend": backend}))
            with self.assertRaises(ValueError):
                self.transfer("backup-state")
        metadata.unlink()
        (metadata.parent / "environment").write_text("other")
        with self.assertRaises(ValueError):
            self.transfer("backup-state")
        self.assertEqual(list(self.shared.iterdir()), [])

    def test_existing_state_lock_or_migration_is_rejected(self):
        for name in (".terraform.tfstate.lock.info", "private/migration-original.tfstate"):
            path = self.project / name
            path.parent.mkdir(exist_ok=True)
            path.write_text("fixture")
            with self.assertRaisesRegex(ValueError, "state lock or migration"):
                self.transfer("backup-state")
            path.unlink()

    def test_wrapper_works_without_vault_or_tofu_and_respects_controller_lock(self):
        for name in ("tofu.sh", "tofu.py", "prepare-bootstrap.py"):
            shutil.copyfile(ROOT / name, self.project / name)
        env = {**os.environ, **self.env}

        def invoke(*args):
            return subprocess.run(["bash", str(self.project / "tofu.sh"), *args],
                                  env=env, capture_output=True, text=True)

        result = invoke("backup-state")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = invoke("restore-state")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(invoke("backup-state", "unexpected-argument").returncode, 0)
        with (self.project / "private/controller.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertNotEqual(invoke("backup-state").returncode, 0)


if __name__ == "__main__":
    unittest.main()
