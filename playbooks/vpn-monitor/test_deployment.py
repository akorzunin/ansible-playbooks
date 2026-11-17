"""Offline checks for the workstation VPN monitor deployment boundary."""

from pathlib import Path
import unittest

import jinja2
import yaml


STACK = Path(__file__).resolve().parent


class DeploymentTests(unittest.TestCase):
    def test_container_is_unprivileged_and_only_publishes_loopback(self):
        rendered = jinja2.Template((STACK / "compose.yml.j2").read_text()).render(
            ansible_facts={"user_uid": 1000, "user_gid": 1000})
        compose = yaml.safe_load(rendered)
        app = compose["services"]["vpn-monitor"]
        self.assertEqual(app["ports"], ["127.0.0.1:8081:8081"])
        self.assertEqual(app["user"], "1000:1000")
        self.assertEqual(app["restart"], "unless-stopped")
        self.assertTrue(app["read_only"])
        self.assertEqual(app["cap_drop"], ["ALL"])
        self.assertNotIn("privileged", app)
        self.assertNotIn("network_mode", app)
        self.assertIn("./data:/app/data", app["volumes"])
        self.assertIn("./config.yaml:/app/config.yaml:ro", app["volumes"])
        self.assertEqual(compose["networks"]["monitoring"]["name"], "ws-logs_default")

    def test_image_contains_only_public_artifacts_and_the_native_core(self):
        dockerfile = (STACK / "Dockerfile").read_text()
        self.assertIn("FROM ghcr.io/sagernet/sing-box@sha256:", dockerfile)
        copies = [line for line in dockerfile.splitlines() if line.startswith("COPY ")]
        self.assertEqual(copies, [
            "COPY bin/vpn-monitor /usr/local/bin/vpn-monitor",
            "COPY web/dist/ web/dist/",
        ])

    def test_private_files_are_suppressed_and_config_is_validated_before_start(self):
        plays = yaml.safe_load((STACK / "deploy.yml").read_text())
        play = plays[0]
        self.assertEqual(play["hosts"], "remote_workstation")
        tasks = play["tasks"]
        names = [task["name"] for task in tasks]
        self.assertLess(names.index("Validate configuration before starting the monitor"),
                        names.index("Start the monitor with persistent history"))
        for task in tasks:
            copy = task.get("ansible.builtin.copy", {})
            if copy.get("mode") == "0600":
                self.assertTrue(task["no_log"])
                self.assertFalse(task["diff"])
        start = next(task["community.docker.docker_compose_v2"] for task in tasks
                     if "community.docker.docker_compose_v2" in task)
        self.assertNotIn("remove_orphans", start)
        self.assertEqual(plays[1]["ansible.builtin.import_playbook"], "../ws-logs/deploy.yml")
        self.assertNotIn("monitoring_replace_ui", plays[1])

    def test_configuration_and_tokens_do_not_depend_on_sibling_private_files(self):
        play = yaml.safe_load((STACK / "deploy.yml").read_text())[0]
        self.assertIn("playbook_dir ~ '/config.yaml'", play["vars"]["vpn_monitor_settings"])
        tasks = [*play["pre_tasks"], *play["tasks"]]
        vault = next(t for t in tasks if "ansible.builtin.include_vars" in t)
        self.assertEqual(vault["ansible.builtin.include_vars"]["file"],
                         "../sing-box-configs/secrets.vault.yaml")
        self.assertTrue(vault["no_log"])
        generate = next(t for t in tasks if t.get("register") == "vpn_monitor_generated")
        self.assertEqual(generate["delegate_to"], "localhost")
        self.assertTrue(generate["no_log"])
        self.assertFalse(generate["changed_when"])
        self.assertIn("sing_box_secrets", generate["ansible.builtin.command"]["stdin"])
        self.assertNotIn("ansible.builtin.ini", (STACK / "deploy.yml").read_text())
        for task in tasks:
            copy = task.get("ansible.builtin.copy", {})
            if copy.get("dest", "").endswith("/.env"):
                self.assertNotIn("src", copy)
                self.assertIn("vpn_monitor_secrets", copy["content"])

    def test_deployment_prefills_before_validation_and_resolution(self):
        tasks = yaml.safe_load((STACK / "deploy.yml").read_text())[0]["pre_tasks"]
        names = [task["name"] for task in tasks]
        prefill = next(task for task in tasks if task.get("register") == "vpn_monitor_prefilled")
        self.assertEqual(prefill["ansible.builtin.command"]["argv"],
                         ["python3", "{{ playbook_dir }}/prefill-servers.py", "--stdin"])
        self.assertIn("sing_box_secrets", prefill["ansible.builtin.command"]["stdin"])
        self.assertIn("vpn_monitor_nodes | default([])", prefill["ansible.builtin.command"]["stdin"])
        self.assertEqual(prefill["delegate_to"], "localhost")
        self.assertFalse(prefill["changed_when"])
        self.assertTrue(prefill["no_log"])
        self.assertEqual(prefill["when"], "vpn_monitor_prefill_servers | default(true) | bool")
        merge = next(task for task in tasks if task["name"].startswith("Use the discovered"))
        self.assertEqual(merge["when"], prefill["when"])
        self.assertTrue(merge["no_log"])
        self.assertIn("combine(vpn_monitor_prefilled.stdout | from_yaml)",
                      merge["ansible.builtin.set_fact"]["vpn_monitor_settings"])
        validate = next(task for task in tasks if task["name"] == "Require a nonempty monitor server list")
        self.assertEqual(validate["ansible.builtin.assert"]["that"], "vpn_monitor_settings.servers | length > 0")
        self.assertLess(names.index("Load shared profile credentials and monitor tokens"), names.index(prefill["name"]))
        self.assertLess(names.index(prefill["name"]), names.index(merge["name"]))
        self.assertLess(names.index(merge["name"]), names.index(validate["name"]))
        self.assertLess(names.index(validate["name"]),
                        names.index("Generate monitor configuration from the tracked settings and shared Vault"))


if __name__ == "__main__":
    unittest.main()
