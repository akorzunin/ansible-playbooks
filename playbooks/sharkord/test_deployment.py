"""Offline checks for the workstation Sharkord deployment."""

import unittest
from pathlib import Path

import yaml

HERE = Path(__file__).parent


class SharkordDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.compose = yaml.safe_load((HERE / "compose.yaml").read_text())
        self.play = yaml.safe_load((HERE / "deploy.yaml").read_text())[0]
        self.service = self.compose["services"]["sharkord"]

    def test_reuses_existing_chat_route_without_changing_caddy(self):
        caddy = (HERE.parent / "pi-caddy" / "Caddyfile").read_text()
        self.assertIn("chat.akorz.duckdns.org {\n    reverse_proxy 192.168.1.132:3333", caddy)
        self.assertIn("192.168.1.132:3333:4991/tcp", self.service["ports"])
        self.assertEqual(self.play["hosts"], "remote_workstation")

    def test_persistent_pinned_single_service_with_media_ports(self):
        self.assertEqual(list(self.compose["services"]), ["sharkord"])
        self.assertRegex(self.service["image"], r":v0\.0\.29@sha256:[a-f0-9]{64}$")
        self.assertEqual(self.service["volumes"], ["./data:/home/bun/.config/sharkord"])
        self.assertIn("40000:40000/tcp", self.service["ports"])
        self.assertIn("40000:40000/udp", self.service["ports"])
        env = self.service["environment"]
        self.assertEqual(env["SHARKORD_AUTOUPDATE"], "false")
        self.assertEqual(env["SHARKORD_ALLOWED_ORIGINS"], "https://chat.akorz.duckdns.org")
        self.assertIn("${SHARKORD_PUBLIC_IP:?", env["SHARKORD_WEBRTC_ANNOUNCED_ADDRESS"])

    def test_private_bootstrap_preserved_and_health_checked(self):
        tasks = self.play["tasks"]
        bootstrap = next(t for t in tasks if "ansible.builtin.shell" in t)
        self.assertTrue(bootstrap["no_log"])
        self.assertIn("umask 077", bootstrap["ansible.builtin.shell"]["cmd"])
        self.assertTrue(bootstrap["ansible.builtin.shell"]["creates"].endswith("/bootstrap.log"))
        directory = next(t["ansible.builtin.file"] for t in tasks if "ansible.builtin.file" in t)
        self.assertEqual(directory["mode"], "0700")
        self.assertNotIn("recurse", directory)
        start = next(t["community.docker.docker_compose_v2"] for t in tasks
                     if "community.docker.docker_compose_v2" in t)
        self.assertTrue(start["wait"])
        https = next(t for t in tasks if t.get("delegate_to") == "localhost")
        self.assertEqual(https["ansible.builtin.uri"]["url"], "https://chat.akorz.duckdns.org/healthz")
        self.assertNotIn("validate_certs", https["ansible.builtin.uri"])


if __name__ == "__main__":
    unittest.main()
