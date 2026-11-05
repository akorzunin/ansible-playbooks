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


if __name__ == "__main__":
    unittest.main()
