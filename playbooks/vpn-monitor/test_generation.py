"""Offline checks for resolving monitor routes without copying profile credentials."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

import yaml


STACK = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("monitor_generate", STACK / "generate.py")
generate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generate)


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.settings = yaml.safe_load((STACK / "config.yaml").read_text())
        self.outbounds = [
            {"tag": f"ge2-{kind}", "type": kind, "server": "example.com", "password": "fixture-secret"}
            for kind in ("ssh", "naive", "vless")
        ]
        self.secrets = {"connections": {}, "extra_outbounds": [
            {"tag": "aurora-vless", "type": "vless"},
            {"tag": "workstation-hop", "type": "ssh"},
            *self.outbounds,
        ]}

    def test_tracked_allowlist_selects_only_ge2_and_preserves_outbound_fields(self):
        original = copy.deepcopy((self.settings, self.secrets))
        config = generate.make_config(self.settings, self.secrets)
        self.assertEqual([server["name"] for server in config["servers"]], ["ge2"])
        protocols = config["servers"][0]["protocols"]
        self.assertEqual([p["name"] for p in protocols], ["ssh", "naive", "vless"])
        self.assertEqual([p["udp"] for p in protocols], [False, False, True])
        for protocol, outbound in zip(protocols, self.outbounds):
            self.assertNotIn("outbound_tag", protocol)
            self.assertEqual(protocol["outbound"], {k: v for k, v in outbound.items() if k != "tag"})
        self.assertEqual((self.settings, self.secrets), original)
        protocols[0]["outbound"]["password"] = "changed"
        self.assertEqual(self.outbounds[0]["password"], "fixture-secret")

    def test_missing_or_duplicate_tag_fails_instead_of_silently_skipping_a_route(self):
        for outbounds in (self.outbounds[1:], [*self.outbounds, self.outbounds[0]]):
            with self.subTest(outbounds=outbounds), self.assertRaises(ValueError):
                generate.make_config(self.settings, {"extra_outbounds": outbounds})

    def test_legacy_connections_are_also_resolved(self):
        config = generate.make_config(self.settings, {
            "connections": {o["type"]: o for o in self.outbounds}, "extra_outbounds": []})
        self.assertEqual(len(config["servers"][0]["protocols"]), 3)

    def test_chains_and_profile_routing_overrides_are_rejected(self):
        for field in generate.ROUTING_OVERRIDES:
            with self.subTest(field=field), self.assertRaises(ValueError):
                generate.make_config(self.settings, {"extra_outbounds": [
                    {**self.outbounds[0], field: "workstation-hop"}, *self.outbounds[1:]]})

    def test_cli_emits_yaml_compatible_json_and_sanitizes_errors(self):
        payload = {"settings": self.settings, "sing_box_secrets": self.secrets}
        result = subprocess.run([sys.executable, str(STACK / "generate.py")],
                                input=json.dumps(payload), capture_output=True, text=True, check=True)
        self.assertEqual(yaml.safe_load(result.stdout), generate.make_config(self.settings, self.secrets))
        payload["settings"]["servers"][0]["protocols"][0]["outbound_tag"] = "fixture-secret"
        result = subprocess.run([sys.executable, str(STACK / "generate.py")],
                                input=json.dumps(payload), capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("fixture-secret", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
