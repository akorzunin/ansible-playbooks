"""Offline bootstrap checks: only temporary inventories are changed, never SSH hosts."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml
from ansible.parsing.vault import VaultLib, VaultSecret
from cryptography.hazmat.primitives import serialization


ROOT = Path(__file__).resolve().parents[2]


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        (self.directory / "ansible.cfg").write_text("[defaults]\n")
        self.source = self.directory / "private-hosts.yml"
        ciphertext = VaultLib([('default', VaultSecret(b'NODE_TEST_VAULT_SECRET'))]).encrypt(b'fixture').decode()
        self.original = ("seed:\n  hosts:\n    old:\n      note: !vault |\n"
                         + "".join("        " + line + "\n" for line in ciphertext.splitlines())
                         + "\n" + (ROOT / "hosts.example.yml").read_text().removeprefix("---\n"))
        self.source.write_text(self.original)
        self.hosts = self.directory / "hosts"
        self.hosts.symlink_to(self.source)
        self.overlay = self.source  # Monitoring and SSH now persist in the same shared inventory.
        self.key = self.directory / "id_ed25519"
        self.key.write_text("unused private key fixture")
        self.key.with_suffix(".pub").write_text("ssh-ed25519 AAAAtest fixture")
        self.vault_password = self.directory / "vault-password"
        self.vault_password.write_text("NODE_TEST_VAULT_SECRET\n")
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
            "node_user": "admin", "node_private_key_file": str(self.key),
            "node_inventory_file": str(self.hosts),
            "NODE_MONITORING_ALLOWED_SOURCES": ["198.51.100.5/32", "2001:db8::1/128"],
            "MONITORING_TELEGRAM_BOT_TOKEN": "fixture",
            "MONITORING_TELEGRAM_CHAT_ID": "-100123",
            "MONITORING_GRAFANA_ADMIN_USER": "admin",
            "MONITORING_GRAFANA_ADMIN_PASSWORD": "GRAFANA_SECRET_FIXTURE",
            "GF_SMTP_USER": "monitoring@example.test",
            "GF_SMTP_PASSWORD": "SMTP_SECRET_FIXTURE",
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
            ["ansible-playbook", "-i", str(self.hosts),
             str(self.playbook), "--vault-password-file", str(self.vault_password),
             "--skip-tags", "node_ssh_readiness",
             "-e", "@" + str(variables_path)],
            cwd=ROOT, env=environment, capture_output=True, text=True, timeout=60,
        )
        self.assertNotIn("ROOT_SECRET_FIXTURE", result.stdout + result.stderr)
        return result

    def monitoring_inventory(self):
        result = subprocess.run(
            ["ansible-inventory", "-i", str(self.hosts), "--list",
             "--vault-password-file", str(self.vault_password)],
            env={**os.environ, "ANSIBLE_CONFIG": str(self.directory / "ansible.cfg")},
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Failed to parse", result.stderr)
        return json.loads(result.stdout)

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
        inventory = self.monitoring_inventory()
        for name in ("new1", "new2"):
            self.assertIn(name, inventory["monitored_nodes"]["hosts"])
            settings = inventory["_meta"]["hostvars"][name]
            self.assertTrue(settings["monitoring_availability_alert"])
            self.assertTrue(settings["monitoring_enabled"])
            self.assertEqual(settings["monitoring_telegraf_allowed_sources"],
                             ["198.51.100.5/32", "2001:db8::1/128"])
        self.assertEqual(set(inventory["retired_nodes"]["hosts"]), {"nt1", "kr1", "sw1", "pl1"})

    def test_portable_keys_are_encrypted_distinct_and_need_no_personal_key_files(self):
        self.key.unlink()
        self.key.with_suffix('.pub').unlink()
        keys = []
        for name in ('new1', 'new2'):
            result = self.run_bootstrap(name)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            raw = yaml.load(self.source.read_text(), Loader=yaml.BaseLoader)
            record = raw['bootstrap_' + name]['hosts'][name]
            self.assertNotIn('ansible_ssh_private_key_file', record)
            ciphertext = record['ansible_private_key']
            self.assertTrue(ciphertext.startswith('$ANSIBLE_VAULT;'))
            private = VaultLib([('default', VaultSecret(b'NODE_TEST_VAULT_SECRET'))]).decrypt(ciphertext)
            serialization.load_ssh_private_key(private, password=None)
            keys.append(private)
            self.assertNotIn(private.decode(), self.source.read_text())
            self.assertNotIn('BEGIN OPENSSH PRIVATE KEY', result.stdout + result.stderr)
        self.assertNotEqual(*keys)
        result = self.run_bootstrap('new1', node_root_pass='')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_wrong_vault_password_does_not_replace_an_existing_identity(self):
        result = self.run_bootstrap()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        saved = self.source.read_text()
        overlay = self.overlay.read_text()
        self.vault_password.write_text('WRONG_SECRET\n')
        result = self.run_bootstrap(node_root_pass='')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.source.read_text(), saved)
        self.assertEqual(self.overlay.read_text(), overlay)

    def test_key_file_migration_is_resumable_and_verified_before_finalizing(self):
        self.source.write_text(self.original + '\n# BEGIN ANSIBLE BOOTSTRAP new1\n'
                               'bootstrap_new1:\n  hosts:\n    new1:\n'
                               '      ansible_host: 192.0.2.10\n'
                               '      ansible_user: admin\n'
                               f'      ansible_ssh_private_key_file: {self.key}\n'
                               '# END ANSIBLE BOOTSTRAP new1\n')
        first = self.run_bootstrap(node_root_pass='')
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        saved = self.source.read_text()
        raw = yaml.load(saved, Loader=yaml.BaseLoader)['bootstrap_new1']['hosts']['new1']
        self.assertEqual(raw['node_bootstrap_legacy_key_file'], str(self.key))
        result = self.run_bootstrap(node_root_pass='')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.source.read_text(), saved)
        plugins = self.directory / 'action_plugins'
        plugins.mkdir()
        (plugins / 'inspect_identity.py').write_text(
            'from ansible.plugins.action import ActionBase\n'
            'from cryptography.hazmat.primitives import serialization\n'
            'class ActionModule(ActionBase):\n'
            '    def run(self, tmp=None, task_vars=None):\n'
            '        v = task_vars\n'
            "        if self._task.args['phase'] == 'legacy':\n"
            "            ok = not v['ansible_private_key'] and v['ansible_ssh_private_key_file'] == v['node_legacy_private_key_file']\n"
            '        else:\n'
            "            key = serialization.load_ssh_private_key(v['ansible_private_key'].encode(), None)\n"
            '            public = key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()\n'
            "            ok = not v['ansible_ssh_private_key_file'] and public == v['node_authorized_key']\n"
            "        return {'changed': False, 'failed': not ok, 'msg': 'Identity transition checked'}\n"
        )
        plays = yaml.safe_load(self.playbook.read_text())
        original = yaml.safe_load((ROOT / 'node/init_node.playbook.yaml').read_text())[2]
        checks = []
        for task in original['pre_tasks']:
            if 'ansible.builtin.setup' in task:
                continue
            if 'ansible.posix.authorized_key' in task:
                task.pop('ansible.posix.authorized_key')
                task['inspect_identity'] = {'phase': 'legacy'}
            if 'ansible.builtin.command' in task:
                task.pop('ansible.builtin.command')
                task['inspect_identity'] = {'phase': 'dedicated'}
            checks.append(task)
        plays[1] = {'hosts': 'node_bootstrap_target', 'gather_facts': False, 'tasks': checks}
        self.playbook.write_text(yaml.safe_dump(plays))
        result = self.run_bootstrap(node_root_pass='', ansible_connection='local')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record = yaml.load(self.source.read_text(), Loader=yaml.BaseLoader)['bootstrap_new1']['hosts']['new1']
        self.assertEqual(record['ansible_private_key'], raw['ansible_private_key'])
        self.assertNotIn('node_bootstrap_legacy_key_file', record)
        self.assertNotIn('ansible_ssh_private_key_file', record)

    def test_defaults_to_shared_workstation_allowlist_when_override_is_empty(self):
        result = self.run_bootstrap(NODE_MONITORING_ALLOWED_SOURCES=[])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Enter allowed monitoring scraper source CIDRs", result.stdout)
        inventory = yaml.load(self.overlay.read_text(), Loader=yaml.BaseLoader)
        expected = inventory["all"]["vars"]["monitoring_workstation_allowed_sources"]
        monitored = self.monitoring_inventory()["_meta"]["hostvars"]
        for name in ("new1", "nk1"):
            self.assertEqual(monitored[name]["monitoring_telegraf_allowed_sources"], expected)

    def test_comment_free_reformatted_inventory_is_preserved_and_extended(self):
        inventory = yaml.load(self.overlay.read_text(), Loader=yaml.BaseLoader)
        # Different indentation/order and no comments or anchors to insert against.
        original = yaml.safe_dump(inventory, indent=4, sort_keys=True)
        self.assertNotIn("# Retain SSH records", original)
        self.overlay.write_text(original)
        result = self.run_bootstrap()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.overlay.read_text().startswith(original))
        parsed = self.monitoring_inventory()
        self.assertIn("new1", parsed["monitored_nodes"]["hosts"])
        self.assertEqual(parsed["monitoring_servers"]["hosts"], ["remote_workstation"])
        self.assertEqual(set(parsed["retired_nodes"]["hosts"]), {"nt1", "kr1", "sw1", "pl1"})
        for name in ("remote_workstation", "remote_pi", "nk1", "dyn1"):
            self.assertIn(name, parsed["monitored_nodes"]["hosts"])

    def test_top_level_monitoring_groups_are_supported(self):
        self.overlay.write_text(
            "monitoring_servers:\n  hosts:\n    remote_workstation:\n"
            "monitored_nodes:\n  hosts:\n    remote_workstation:\n"
        )
        original = self.overlay.read_text()
        result = self.run_bootstrap()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.overlay.read_text().startswith(original))
        inventory = self.monitoring_inventory()
        self.assertIn("new1", inventory["monitored_nodes"]["hosts"])
        settings = inventory["_meta"]["hostvars"]["new1"]
        self.assertTrue(settings["monitoring_enabled"])
        self.assertEqual(settings["monitoring_client_telegraf_port"], 9273)

    def test_existing_layout_dependent_entries_are_migrated(self):
        result = self.run_bootstrap()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # Simulate a previous bootstrap's indented managed monitoring block.
        original = self.source.read_text()
        legacy = (
            "        # BEGIN ANSIBLE MONITORING new1\n"
            "        new1:\n"
            "          monitoring_availability_alert: true\n"
            "          monitoring_telegraf_allowed_sources: [198.51.100.5/32]\n"
            "        # END ANSIBLE MONITORING new1\n"
        )
        self.overlay.write_text(original.replace("    # Retain SSH records", legacy + "    # Retain SSH records"))
        result = self.run_bootstrap(node_root_pass="")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        saved = self.overlay.read_text()
        self.assertNotIn(legacy, saved)
        self.assertEqual(saved.count("# BEGIN ANSIBLE MONITORING new1"), 1)
        self.assertEqual(saved.count("# BEGIN ANSIBLE BOOTSTRAP new1"), 1)
        self.assertTrue(saved.startswith(original))
        self.assertIn("new1", self.monitoring_inventory()["monitored_nodes"]["hosts"])
        result = self.run_bootstrap(node_root_pass="")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.overlay.read_text(), saved)

    def test_unsafe_inputs_fail_before_inventory_changes(self):
        for overrides in (
            {"nn": "old"}, {"nn": "bad name"}, {"node_address": "host\ninjected: true"},
            {"node_user": "root"}, {"node_monitoring_allowed_sources": ["0.0.0.0/0"]},
            {"node_monitoring_allowed_sources": ["1.2.3.4/0"]},
            {"node_monitoring_allowed_sources": ["not-a-network"]},
            {"MONITORING_TELEGRAM_BOT_TOKEN": ""},
            {"MONITORING_GRAFANA_ADMIN_PASSWORD": ""},
            {"GF_SMTP_USER": ""}, {"GF_SMTP_USER": "not-an-email"},
            {"GF_SMTP_PASSWORD": ""},
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

    def test_connection_reuse_is_disabled_only_for_fresh_access_checks(self):
        plugins = self.directory / "action_plugins"
        plugins.mkdir()
        (plugins / "inspect_connection.py").write_text(
            "from ansible.plugins.action import ActionBase\n"
            "class ActionModule(ActionBase):\n"
            "    def run(self, tmp=None, task_vars=None):\n"
            "        return {'changed': False, 'ssh_args': task_vars['ansible_ssh_args'],\n"
            "                'ssh_retries': task_vars['ansible_ssh_retries']}\n"
        )
        original = yaml.safe_load((ROOT / "node/init_node.playbook.yaml").read_text())[2]
        checks = [task for task in original["pre_tasks"] + original["tasks"]
                  if task.get("ansible.builtin.command") == "/usr/bin/true"]
        self.assertEqual(len(checks), 2)
        tasks = [{"inspect_connection": {}, "register": "normal"}]
        assertions = ["'ControlMaster=auto' in normal.ssh_args", "normal.ssh_retries == 3"]
        for index, check in enumerate(checks):
            register = f"checked_{index}"
            tasks.append({
                "name": check["name"], "inspect_connection": {},
                "vars": check["vars"], "register": register,
            })
            for option in ("ControlMaster=no", "ControlPath=none", "IdentitiesOnly=yes",
                           "PreferredAuthentications=publickey", "PasswordAuthentication=no"):
                assertions.append(f"'{option}' in {register}.ssh_args")
        tasks.append({"ansible.builtin.assert": {"that": assertions}})
        plays = yaml.safe_load(self.playbook.read_text())
        plays[1] = {"hosts": "node_bootstrap_target", "gather_facts": False, "tasks": tasks}
        self.playbook.write_text(yaml.safe_dump(plays))
        result = self.run_bootstrap()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        prepare = yaml.safe_load((ROOT / "roles/node/tasks/prepare_node.yaml").read_text())
        root = next(task["ansible.builtin.add_host"] for task in prepare
                    if task["name"] == "Add temporary root connection only when a password is supplied")
        self.assertIn("ControlMaster=auto", root["ansible_ssh_args"])
        self.assertIn("PubkeyAuthentication=no", root["ansible_ssh_args"])

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
