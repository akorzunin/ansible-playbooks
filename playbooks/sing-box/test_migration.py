"""Offline migration safeguards plus config checks with the cached pinned image."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import jinja2
import yaml


ROOT = Path(__file__).resolve().parent
COMPOSE = yaml.safe_load((ROOT / "compose.yaml").read_text())
PLAY = yaml.safe_load((ROOT / "deploy.yaml").read_text())[0]
IMAGE = COMPOSE["services"]["sing-box"]["image"]


def vless():
    # Synthetic credentials and public test key, never real Vault inputs.
    return {
        "type": "vless", "tag": "ge2-vless", "server": "example.com",
        "server_port": 443, "uuid": "00000000-0000-4000-8000-000000000001",
        "flow": "xtls-rprx-vision",
        "tls": {"enabled": True, "server_name": "example.com",
                "utls": {"enabled": True, "fingerprint": "firefox"},
                "reality": {"enabled": True, "short_id": "0123456789abcdef",
                            "public_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}},
    }


def render(outbound):
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["to_nice_json"] = lambda value: json.dumps(value, indent=4)
    return env.from_string((ROOT / "config.json.j2").read_text()).render(
        ge2_outbounds=[outbound]
    )


class ConfigurationTests(unittest.TestCase):
    def test_ge2_outbound_preserved_without_aurora_ge1_or_direct_fallback(self):
        outbound = vless()
        config = json.loads(render(outbound))
        self.assertEqual(config["outbounds"], [outbound])
        self.assertEqual(config["route"], {
            "final": "ge2-vless", "default_domain_resolver": "local"})
        self.assertNotIn("insecure", config["outbounds"][0]["tls"])
        self.assertNotIn("experimental", config)

    def test_legacy_listener_ports(self):
        config = json.loads(render(vless()))
        self.assertEqual(
            [(item["type"], item["listen"], item["listen_port"])
             for item in config["inbounds"]],
            [("mixed", "0.0.0.0", 20171), ("socks", "0.0.0.0", 20170)],
        )

    def test_restricted_container_keeps_host_gateway_clients_and_alias(self):
        service = COMPOSE["services"]["sing-box"]
        self.assertIn("@sha256:", service["image"])
        self.assertEqual(service["ports"], ["20171:20171", "20170:20170"])
        self.assertEqual(service["networks"]["v2raya-proxy"]["aliases"], ["v2raya"])
        self.assertEqual(service["volumes"], ["./config.json:/etc/sing-box/config.json:ro"])
        self.assertTrue(service["read_only"])
        self.assertEqual(service["cap_drop"], ["ALL"])
        self.assertNotIn("privileged", service)
        self.assertNotIn("network_mode", service)


class MigrationSafeguardTests(unittest.TestCase):
    def test_shared_vault_selection_and_workstation_scope(self):
        self.assertEqual(PLAY["hosts"], "remote_workstation")
        credentials = PLAY["pre_tasks"][1]
        self.assertEqual(credentials["ansible.builtin.include_vars"]["file"],
                         "../sing-box-configs/secrets.vault.yaml")
        self.assertTrue(credentials["no_log"])
        self.assertIn("selectattr('tag', 'equalto', 'ge2-vless')",
                      PLAY["vars"]["ge2_outbounds"])
        validation = PLAY["pre_tasks"][2]
        self.assertTrue(validation["no_log"])
        self.assertIn("ge2_outbounds | length == 1",
                      validation["ansible.builtin.assert"]["that"])
        self.assertIn("ge2_outbounds[0].type == 'vless'",
                      validation["ansible.builtin.assert"]["that"])
        self.assertIn("ge2_outbounds[0].detour is not defined",
                      validation["ansible.builtin.assert"]["that"])

    def test_shared_vault_excludes_blocked_and_unrelated_routes(self):
        env = jinja2.Environment(undefined=jinja2.StrictUndefined)
        select = env.compile_expression(PLAY["vars"]["ge2_outbounds"].strip()[2:-2])
        outbound = vless()
        selected = select(sing_box_secrets={"extra_outbounds": [
            {**outbound, "tag": "aurora-vless"},
            {**outbound, "tag": "ge1-vless"},
            {"type": "naive", "tag": "ge2-naive"},
            outbound,
        ]})
        self.assertEqual(selected, [outbound])
        self.assertEqual(json.loads(render(selected[0]))["outbounds"], [outbound])

    def test_candidate_validated_before_activation(self):
        tasks = PLAY["tasks"]
        candidate = next(i for i, task in enumerate(tasks)
                         if "ansible.builtin.template" in task)
        activation = next(i for i, task in enumerate(tasks) if "block" in task)
        self.assertLess(candidate, activation)
        task = tasks[candidate]
        self.assertIn("check -c", task["ansible.builtin.template"]["validate"])
        self.assertIn("{{ sing_box_image }}", task["ansible.builtin.template"]["validate"])
        self.assertTrue(task["no_log"])
        self.assertFalse(task["diff"])
        self.assertEqual(task["ansible.builtin.template"]["mode"], "0600")

    def test_cutover_health_and_rollback_order(self):
        states = next(task for task in PLAY["tasks"] if "register" in task
                      and task["register"] == "previous_containers")
        self.assertEqual(states["loop"], ["v2raya", "v2raya-ssh-socks", "sing-box"])
        activation = next(task for task in PLAY["tasks"] if "block" in task)
        block = activation["block"]
        stop = block[2]
        self.assertEqual(stop["ansible.builtin.command"]["argv"][:2], ["docker", "stop"])
        self.assertEqual(stop["loop"], "{{ previous_containers.results[:2] }}")
        self.assertEqual(stop["when"], "item.stdout == 'true'")
        self.assertIn("--force-recreate", block[3]["ansible.builtin.command"]["cmd"])
        health = block[-1]
        self.assertTrue(health["ansible.builtin.uri"]["use_proxy"])
        self.assertTrue(health["ansible.builtin.uri"]["validate_certs"])
        self.assertEqual(health["environment"]["https_proxy"], "http://127.0.0.1:20171")
        self.assertEqual(health["environment"]["NO_PROXY"], "")
        rescue = activation["rescue"]
        self.assertIn("down", rescue[0]["ansible.builtin.command"]["cmd"])
        self.assertIn("backup_file", rescue[1]["ansible.builtin.copy"]["src"])
        self.assertEqual(rescue[2]["when"], "previous_containers.results[2].stdout == 'true'")
        self.assertIn("reverse", rescue[-2]["loop"])
        self.assertIn("ansible.builtin.fail", rescue[-1])


class PinnedImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("docker"):
            raise unittest.SkipTest("Docker is not installed")
        result = subprocess.run(["docker", "image", "inspect", IMAGE],
                                capture_output=True, timeout=10)
        if result.returncode:
            raise unittest.SkipTest("Pinned image not cached or Docker unavailable")

    def check_config(self, outbound):
        with tempfile.TemporaryDirectory(prefix="workstation-sing-box-test-") as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(render(outbound))
            return subprocess.run(
                ["docker", "run", "--rm", "--network=none", "-v",
                 f"{path}:/etc/sing-box/config.json:ro", IMAGE,
                 "check", "-c", "/etc/sing-box/config.json"],
                capture_output=True, text=True, timeout=30,
            )

    def test_ge2_vless_shape_validates(self):
        result = self.check_config(vless())
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_reality_key_rejected(self):
        outbound = vless()
        outbound["tls"]["reality"]["public_key"] = "invalid-key"
        result = self.check_config(outbound)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
