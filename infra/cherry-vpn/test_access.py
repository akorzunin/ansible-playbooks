"""Verify replacement refreshes manual SSH access without touching real inventories."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

PROJECT = Path(__file__).resolve().parent


class CherryAccessTests(unittest.TestCase):
    def test_replacement_updates_one_managed_block_preserving_vault_and_symlink(self):
        plays = yaml.safe_load((PROJECT / "deploy.yaml").read_text())
        self.assertIn("vpn-probe/deploy.yaml", plays[0]["ansible.builtin.import_playbook"])
        self.assertEqual(plays[1]["hosts"], "vpn_test_admin")
        task = plays[1]["pre_tasks"][0]
        self.assertEqual(task["delegate_to"], "localhost")
        self.assertFalse(task["become"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "infra/cherry-vpn"
            project.mkdir(parents=True)
            source = root / "private-hosts"
            original = "seed:\n  hosts:\n    old:\n      password: !vault |\n        ciphertext-fixture\n"
            source.write_text(original)
            (root / "hosts").symlink_to(source)
            config = root / "ansible.cfg"
            config.write_text("[defaults]\n")
            playbook = project / "persist.yaml"
            playbook.write_text(yaml.safe_dump([{
                "name": "Offline access persistence", "hosts": "localhost",
                "connection": "local", "gather_facts": False, "tasks": [task],
            }]))
            variables = {
                "ansible_host": "192.0.2.1", "ansible_user": "vpnadmin",
                "ansible_ssh_private_key_file": "/private/admin",
                "ansible_ssh_common_args": "-o StrictHostKeyChecking=yes -o UserKnownHostsFile=/private/known_hosts",
            }

            def persist():
                result = subprocess.run(
                    ["ansible-playbook", "-i", "localhost,", str(playbook), "-e", json.dumps(variables)],
                    env={**os.environ, "ANSIBLE_CONFIG": str(config)},
                    capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            persist()
            first = source.read_text()
            persist()
            self.assertEqual(source.read_text(), first)
            variables.update(ansible_host="192.0.2.2", ansible_ssh_private_key_file="/new path/admin",
                             ansible_ssh_common_args="-o StrictHostKeyChecking=yes -o UserKnownHostsFile='/new path/known_hosts'")
            persist()
            saved = source.read_text()
            self.assertTrue((root / "hosts").is_symlink())
            self.assertTrue(saved.startswith(original))
            self.assertEqual(saved.count("# BEGIN ANSIBLE BOOTSTRAP dyn1"), 1)
            self.assertNotIn("192.0.2.1", saved)
            # Ignore the unrelated Vault-tagged prefix, which must remain byte-for-byte intact.
            host = yaml.safe_load(saved[len(original):])["bootstrap_dyn1"]["hosts"]["dyn1"]
            self.assertEqual(host["ansible_port"], 22)
            for key, value in variables.items():
                self.assertEqual(host[key], value)


if __name__ == "__main__":
    unittest.main()
