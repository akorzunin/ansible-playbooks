"""Offline bootstrap checks: only temporary inventories are changed, never SSH hosts."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        (self.directory / "ansible.cfg").write_text("[defaults]\n")
        self.source = self.directory / "private-hosts.yml"
        self.original = "seed:\n  hosts:\n    old:\n      note: !vault |\n        encrypted-fixture\n"
        self.source.write_text(self.original)
        self.hosts = self.directory / "hosts"
        self.hosts.symlink_to(self.source)
        self.overlay = self.directory / "monitoring.yml"
        self.overlay.write_text((ROOT / "monitoring.inventory.yml.example").read_text())
        self.key = self.directory / "id_ed25519"
        self.key.write_text("unused private key fixture")
        self.key.with_suffix(".pub").write_text("ssh-ed25519 AAAAtest fixture")
        self.env_file = self.directory / ".env"
        self.env_file.write_text("UNUSED=fixture\n")
        self.playbook = self.directory / "offline.yml"
        self.playbook.write_text(yaml.safe_dump([
            {
                "name": "Prepare only; no remote bootstrap",
                "hosts": "localhost", "connection": "local", "gather_facts": False,
                "tasks": [{"ansible.builtin.import_role": {"name": "node", "tasks_from": "prepare_node"}}],
            },
            {
                "name": "Persist only; all tasks delegate locally",
                "hosts": "node_bootstrap_target", "gather_facts": False,
                "tasks": [{"ansible.builtin.import_role": {"name": "node", "tasks_from": "persist_node"}}],
            },
        ]))

    def run_bootstrap(self, name="new1", **overrides):
        variables = {
            "nn": name, "node_address": "192.0.2.10", "node_root_pass": "ROOT_SECRET_FIXTURE",
            "node_user": "admin", "node_public_key_file": str(self.key.with_suffix(".pub")),
            "node_inventory_file": str(self.hosts),
            "node_monitoring_inventory_file": str(self.overlay),
            "monitoring_env_file": str(self.env_file),
            "NODE_MONITORING_ALLOWED_SOURCES": ["198.51.100.5/32", "2001:db8::1/128"],
            "MONITORING_TELEGRAM_BOT_TOKEN": "fixture",
            "MONITORING_TELEGRAM_CHAT_ID": "-100123",
            **overrides,
        }
        variables_path = self.directory / "vars.json"
        variables_path.write_text(json.dumps(variables))
        environment = {
            **os.environ,
            "ANSIBLE_ROLES_PATH": str(ROOT / "roles"),
            "ANSIBLE_LOCAL_TEMP": str(self.directory / "local-tmp"),
            "ANSIBLE_REMOTE_TEMP": str(self.directory / "remote-tmp"),
            "ANSIBLE_CONFIG": str(self.directory / "ansible.cfg"),
            "ANSIBLE_NOCOLOR": "1",
        }
        result = subprocess.run(
            ["ansible-playbook", "-i", str(self.hosts), "-i", str(self.overlay),
             str(self.playbook), "--skip-tags", "node_ssh_readiness",
             "-e", "@" + str(variables_path)],
            cwd=ROOT, env=environment, capture_output=True, text=True, timeout=60,
        )
        self.assertNotIn("ROOT_SECRET_FIXTURE", result.stdout + result.stderr)
        return result

    def test_persistence_is_idempotent_preserves_symlink_and_adds_multiple_nodes(self):
        first = self.run_bootstrap()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        saved = self.source.read_text()
        overlay = self.overlay.read_text()
        self.assertTrue(self.hosts.is_symlink())
        self.assertTrue(saved.startswith(self.original))
        self.assertNotIn("ROOT_SECRET_FIXTURE", saved + overlay)
        self.assertNotIn("ansible_password", saved)
        self.assertIn('ansible_user: "admin"', saved)
        self.assertIn("ansible_python_interpreter: /usr/bin/python3", saved)
        repeated = self.run_bootstrap(node_root_pass="")
        self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
        self.assertEqual(self.source.read_text(), saved)
        self.assertEqual(self.overlay.read_text(), overlay)
        second = self.run_bootstrap("new2")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        inventory = yaml.safe_load(self.overlay.read_text())
        monitored = inventory["all"]["children"]["monitored_nodes"]["hosts"]
        for name in ("new1", "new2"):
            self.assertTrue(monitored[name]["monitoring_availability_alert"])
            self.assertEqual(monitored[name]["monitoring_telegraf_allowed_sources"],
                             ["198.51.100.5/32", "2001:db8::1/128"])
        self.assertEqual(set(inventory["all"]["children"]["retired_nodes"]["hosts"]),
                         {"kr1", "sw1", "pl1"})

    def test_defaults_to_shared_workstation_allowlist_when_override_is_empty(self):
        result = self.run_bootstrap(NODE_MONITORING_ALLOWED_SOURCES=[])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Enter allowed monitoring scraper source CIDRs", result.stdout)
        inventory = yaml.safe_load(self.overlay.read_text())
        expected = inventory["all"]["vars"]["monitoring_workstation_allowed_sources"]
        monitored = inventory["all"]["children"]["monitored_nodes"]["hosts"]
        for name in ("new1", "nk1", "nt1"):
            self.assertEqual(monitored[name]["monitoring_telegraf_allowed_sources"], expected)

    def test_unsafe_inputs_fail_before_inventory_changes(self):
        for overrides in (
            {"nn": "old"}, {"nn": "bad name"}, {"node_address": "host\ninjected: true"},
            {"node_user": "root"}, {"node_monitoring_allowed_sources": ["0.0.0.0/0"]},
            {"node_monitoring_allowed_sources": ["1.2.3.4/0"]},
            {"node_monitoring_allowed_sources": ["not-a-network"]},
            {"MONITORING_TELEGRAM_BOT_TOKEN": ""},
        ):
            with self.subTest(overrides=overrides):
                result = self.run_bootstrap(**overrides)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("FAILED", result.stdout, result.stdout + result.stderr)
                self.assertEqual(self.source.read_text(), self.original)
                self.assertNotIn("ANSIBLE BOOTSTRAP", self.overlay.read_text())

    def test_monitoring_runs_only_after_successful_bootstrap(self):
        plugins = self.directory / "action_plugins"
        plugins.mkdir()
        (plugins / "offline_unreachable.py").write_text(
            "from ansible.plugins.action import ActionBase\n"
            "class ActionModule(ActionBase):\n"
            "    def run(self, tmp=None, task_vars=None):\n"
            "        return {'unreachable': True, 'msg': 'simulated SSH banner timeout'}\n"
        )
        marker = self.directory / "monitoring-was-modified"
        monitoring = self.directory / "mock-monitoring.yml"
        monitoring.write_text(yaml.safe_dump([{
            "name": "Mock monitoring deployment", "hosts": "localhost",
            "connection": "local", "gather_facts": True,
            "tasks": [{"ansible.builtin.copy": {"dest": str(marker), "content": "changed"}}],
        }]))
        original = yaml.safe_load((ROOT / "node/init_node.playbook.yaml").read_text())
        for stage in ("root", "administrator", "success"):
            with self.subTest(stage=stage):
                plays = yaml.safe_load(yaml.safe_dump(original[:-1]))
                plays[0] = {
                    "hosts": "localhost", "connection": "local", "gather_facts": False,
                    "tasks": [
                        {"ansible.builtin.set_fact": {
                            "node_bootstrap_root_ready": False, "node_bootstrap_ready": False}},
                        {"ansible.builtin.add_host": {"name": "new1_root",
                         "groups": "node_bootstrap_root", "ansible_connection": "local"}},
                        {"ansible.builtin.add_host": {"name": "new1",
                         "groups": "node_bootstrap_target", "ansible_connection": "local"}},
                    ],
                }
                plays[1]["tasks"] = (
                    [{"offline_unreachable": {}}] if stage == "root"
                    else [plays[1]["tasks"][-1]]
                )
                plays[2]["become"] = False
                plays[2]["pre_tasks"] = [plays[2]["pre_tasks"][0]]
                if stage == "success":
                    plays[2]["tasks"] = [plays[2]["tasks"][-1]]
                else:
                    plays[2]["pre_tasks"].append({"offline_unreachable": {}})
                    plays[2]["tasks"] = [{"ansible.builtin.fail": {"msg": "UNSAFE_NODE_SETUP"}}]
                plays[3]["ansible.builtin.import_playbook"] = str(monitoring)
                self.playbook.write_text(yaml.safe_dump(plays))
                result = self.run_bootstrap()
                if stage == "success":
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertTrue(marker.exists(), result.stdout + result.stderr)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("simulated SSH banner timeout", result.stdout, result.stdout + result.stderr)
                    self.assertFalse(marker.exists(), result.stdout + result.stderr)
                self.assertNotIn("UNSAFE_NODE_SETUP", result.stdout)
                self.assertEqual(self.source.read_text(), self.original)

    def test_verification_precedes_ssh_hardening_and_no_password_debug_remains(self):
        plays = yaml.safe_load((ROOT / "node/init_node.playbook.yaml").read_text())
        setup = plays[2]
        key_check = next(task for task in setup["pre_tasks"] if "ansible.builtin.command" in task)
        self.assertIn("key-only", key_check["name"])
        self.assertEqual(key_check["ansible.builtin.command"], "/usr/bin/true")
        self.assertTrue(setup["become"])
        self.assertTrue(all(play.get("any_errors_fatal") for play in plays if "hosts" in play))
        policy_tasks = yaml.safe_load((ROOT / "roles/node/tasks/setup_node.yaml").read_text())
        policy = next(task["ansible.builtin.blockinfile"] for task in policy_tasks
                      if "ansible.builtin.blockinfile" in task)
        self.assertEqual(policy["insertbefore"], "BOF")
        self.assertIn("sshd -t", policy["validate"])
        for directive in ("PermitRootLogin no", "PasswordAuthentication no",
                          "KbdInteractiveAuthentication no"):
            self.assertIn(directive, policy["block"])
        self.assertNotIn("node_root_pass", (ROOT / "roles/node/tasks/main.yaml").read_text())


if __name__ == "__main__":
    unittest.main()
