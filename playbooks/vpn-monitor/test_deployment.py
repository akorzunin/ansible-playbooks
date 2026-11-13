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
        echo = yaml.safe_load((STACK / "echo-ge2.yml").read_text())[0]
        self.assertIn("vpn_monitor_secrets", echo["vars"]["vpn_monitor_udp_token"])
        self.assertNotIn("ansible.builtin.ini", (STACK / "echo-ge2.yml").read_text())

    def test_ge2_echo_is_authenticated_sandboxed_and_port_scoped(self):
        play, = yaml.safe_load((STACK / "echo-ge2.yml").read_text())
        self.assertEqual(play["hosts"], "ge2")
        copies = {task["ansible.builtin.copy"]["dest"]: task
                  for task in play["tasks"] if "ansible.builtin.copy" in task}
        secret = copies["/etc/vpn-monitor/echo.env"]
        self.assertEqual(secret["ansible.builtin.copy"]["mode"], "0600")
        self.assertTrue(secret["no_log"])
        self.assertFalse(secret["diff"])
        unit = copies["/etc/systemd/system/vpn-monitor-echo.service"]["ansible.builtin.copy"]["content"]
        self.assertIn("DynamicUser=yes", unit)
        self.assertIn("ProtectSystem=strict", unit)
        self.assertIn("EnvironmentFile=/etc/vpn-monitor/echo.env", unit)
        self.assertIn("ExecStartPre=+/usr/sbin/nft -f /etc/vpn-monitor/echo.nft", unit)
        self.assertIn("--echo --echo-listen 94.249.187.177:9444", unit)
        firewall = copies["/etc/vpn-monitor/echo.nft"]["ansible.builtin.copy"]["content"]
        self.assertNotIn("flush ruleset", firewall)
        self.assertIn("flush table inet vpn_monitor_echo", firewall)
        self.assertIn("limit rate 100/second", firewall)
        self.assertIn("94.249.186.199", firewall)
        self.assertIn("172.22.0.0/16", firewall)
        rules = [line for line in firewall.splitlines() if line.startswith("add rule")]
        self.assertTrue(all("udp dport 9444" in line for line in rules))
        self.assertTrue(rules[-1].endswith("drop"))


if __name__ == "__main__":
    unittest.main()
