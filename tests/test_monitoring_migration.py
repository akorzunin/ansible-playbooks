"""Consolidating inventories must preserve Vault text and effective membership."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "playbooks/ws-logs/migrate-inventory.py"


class MonitoringMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "shared-hosts"
        self.original = "seed:\n  hosts:\n    existing:\n      note: !vault |\n        encrypted-fixture\n"
        self.source.write_text(self.original)
        self.hosts = self.root / "hosts"
        self.hosts.symlink_to(self.source)
        self.overlay = self.root / "monitoring.yml"
        self.overlay.write_text((ROOT / "hosts.example.yml").read_text())
        self.backup = self.source.with_name(self.source.name + ".monitoring-backup~")

    def migrate(self):
        return subprocess.run(
            [sys.executable, "-B", str(MIGRATION), "--hosts", str(self.hosts), "--overlay", str(self.overlay)],
            capture_output=True, text=True, timeout=20)

    def test_merge_preserves_symlink_vault_comments_and_backup(self):
        overlay = self.overlay.read_text()
        result = self.migrate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.hosts.is_symlink())
        self.assertTrue(self.source.read_text().startswith(self.original))
        self.assertEqual(self.backup.read_text(), self.original)
        self.assertEqual(self.source.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.backup.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.overlay.read_text(), overlay)
        expected = {**yaml.load(self.original, Loader=yaml.BaseLoader),
                    **yaml.load(overlay, Loader=yaml.BaseLoader)}
        self.assertEqual(yaml.load(self.source.read_text(), Loader=yaml.BaseLoader), expected)
        merged = self.source.read_text()
        result = self.migrate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.source.read_text(), merged)
        self.assertEqual(self.backup.read_text(), self.original)

    def test_bootstrap_markers_no_longer_collide_with_ssh_identity_blocks(self):
        self.source.write_text(self.original + "# BEGIN ANSIBLE BOOTSTRAP new1\n"
                               "bootstrap_new1:\n  hosts:\n    new1:\n      ansible_user: admin\n"
                               "# END ANSIBLE BOOTSTRAP new1\n")
        self.overlay.write_text("# BEGIN ANSIBLE BOOTSTRAP new1\n"
                                "monitoring_bootstrap_new1:\n  children:\n    monitored_nodes:\n      hosts:\n        new1:\n"
                                "# END ANSIBLE BOOTSTRAP new1\n")
        result = self.migrate()
        self.assertEqual(result.returncode, 0, result.stderr)
        merged = self.source.read_text()
        self.assertEqual(merged.count("# BEGIN ANSIBLE BOOTSTRAP new1"), 1)
        self.assertEqual(merged.count("# BEGIN ANSIBLE MONITORING new1"), 1)

    def test_overlapping_roots_refuse_to_drop_existing_settings(self):
        self.overlay.write_text("seed:\n  hosts:\n    other:\n")
        result = self.migrate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Overlapping", result.stderr)
        self.assertEqual(self.source.read_text(), self.original)
        self.assertFalse(self.backup.exists())

    def test_invalid_yaml_does_not_echo_private_contents_or_change_files(self):
        self.overlay.write_text("all: [PRIVATE_SECRET_FIXTURE\n")
        result = self.migrate()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("PRIVATE_SECRET_FIXTURE", result.stdout + result.stderr)
        self.assertEqual(self.source.read_text(), self.original)
        self.assertFalse(self.backup.exists())

    def test_existing_backup_is_never_overwritten(self):
        self.backup.write_text("keep backup\n")
        result = self.migrate()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.source.read_text(), self.original)
        self.assertEqual(self.backup.read_text(), "keep backup\n")

    @unittest.skipUnless(shutil.which("ansible-inventory"), "Ansible is needed for effective inventory comparison")
    def test_single_inventory_has_same_effective_settings_as_old_two_inventories(self):
        self.source.write_text("seed:\n  hosts:\n    nk1:\n      ansible_host: ssh.example.test\n")
        config = self.root / "ansible.cfg"
        config.write_text("[defaults]\n")

        def inventory(*paths):
            args = ["ansible-inventory", "--list"]
            for path in paths:
                args.extend(["-i", str(path)])
            result = subprocess.run(args, env={**os.environ, "ANSIBLE_CONFIG": str(config)},
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)

        before = inventory(self.hosts, self.overlay)
        result = self.migrate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(inventory(self.hosts), before)


if __name__ == "__main__":
    unittest.main()
