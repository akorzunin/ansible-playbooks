"""Offline allowlist discovery and safe local-write tests; no real Vault access."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml


STACK = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("prefill_servers", STACK / "prefill-servers.py")
prefill = importlib.util.module_from_spec(spec)
# Match invoking the script directly, including its sibling generate.py import.
sys.path.insert(0, str(STACK))
try:
    spec.loader.exec_module(prefill)
    from generate import make_config
finally:
    sys.path.pop(0)


class PrefillTests(unittest.TestCase):
    def setUp(self):
        self.secrets = {"connections": {}, "extra_outbounds": [
            {"tag": f"{node}-{kind}", "type": kind, "password": "fixture-secret"}
            for node in ("dyn2", "dyn1") for kind in ("vless", "ssh", "naive")
        ]}

    def test_groups_nodes_without_credentials_and_resolves_with_existing_generator(self):
        original = copy.deepcopy(self.secrets)
        servers = prefill.discover_servers(self.secrets)
        self.assertEqual([s["name"] for s in servers], ["dyn1", "dyn2"])
        for server in servers:
            self.assertEqual([p["name"] for p in server["protocols"]], ["naive", "ssh", "vless"])
            self.assertTrue(all(not p["udp"] for p in server["protocols"]))
        self.assertNotIn("fixture-secret", yaml.safe_dump(servers))
        self.assertEqual(self.secrets, original)
        config = make_config({"servers": servers}, self.secrets)
        self.assertEqual(config["servers"][0]["protocols"][0]["outbound"]["password"], "fixture-secret")

    def test_skips_chains_hops_routing_overrides_and_profile_pseudo_outbounds(self):
        self.secrets["extra_outbounds"] += [
            {"tag": "workstation-hop", "type": "ssh"},
            {"tag": "dyn2-vless-via-naive", "type": "vless", "detour": "dyn2-naive"},
            {"tag": "proxy", "type": "selector"},
            {"tag": "direct", "type": "direct"},
            {"tag": "unrecognized-alias", "type": "vless"},
            *[{"tag": f"override{i}-vless", "type": "vless", field: "private"}
              for i, field in enumerate(prefill.ROUTING_OVERRIDES)],
        ]
        self.assertEqual([s["name"] for s in prefill.discover_servers(self.secrets)], ["dyn1", "dyn2"])

    def test_filters_nodes_and_includes_legacy_connections(self):
        self.secrets["connections"] = {"ssh": {"tag": "ssh", "type": "ssh"}}
        self.assertEqual([s["name"] for s in prefill.discover_servers(self.secrets)], ["default", "dyn1", "dyn2"])
        self.assertEqual([s["name"] for s in prefill.discover_servers(self.secrets, ["dyn2"])], ["dyn2"])
        with self.assertRaises(ValueError):
            prefill.discover_servers(self.secrets, ["dyn2", "missing"])

    def test_rejects_duplicates_empty_invalid_names_and_excess_routes(self):
        for secrets in (
            {},
            {"extra_outbounds": [self.secrets["extra_outbounds"][0]] * 2},
            {"extra_outbounds": [{"tag": "bad/name-vless", "type": "vless"}]},
            {"extra_outbounds": [{"tag": f"node{i}-vless", "type": "vless"} for i in range(65)]},
        ):
            with self.subTest(secrets=secrets), self.assertRaises(ValueError):
                prefill.discover_servers(secrets)

    def test_stdin_mode_uses_loaded_vault_without_decrypting_or_writing(self):
        command = [sys.executable, str(STACK / "prefill-servers.py"), "--stdin"]
        payload = {"sing_box_secrets": self.secrets, "nodes": ["dyn2"]}
        result = subprocess.run(command, input=json.dumps(payload), text=True, capture_output=True,
                                env={**os.environ, "PATH": ""}, check=True)
        self.assertEqual([s["name"] for s in yaml.safe_load(result.stdout)["servers"]], ["dyn2"])
        self.assertNotIn("fixture-secret", result.stdout + result.stderr)
        payload.pop("nodes")
        result = subprocess.run(command, input=json.dumps(payload), text=True, capture_output=True, check=True)
        self.assertEqual(len(yaml.safe_load(result.stdout)["servers"]), 2)
        for nodes in ("dyn2", None, ["missing"], [42]):
            payload["nodes"] = nodes
            result = subprocess.run(command, input=json.dumps(payload), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("fixture-secret", result.stdout + result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_write_preserves_other_settings_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as work:
            path = Path(work) / "config.yaml"
            original = yaml.safe_load((STACK / "config.yaml").read_text())
            path.write_text(yaml.safe_dump(original))
            path.chmod(0o640)
            servers = prefill.discover_servers(self.secrets)
            self.assertTrue(prefill.update_settings(path, servers))
            updated = yaml.safe_load(path.read_text())
            self.assertEqual(updated, {**original, "servers": servers})
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            before = path.stat().st_mtime_ns
            self.assertFalse(prefill.update_settings(path, servers))
            self.assertEqual(path.stat().st_mtime_ns, before)

    def test_cli_preview_write_and_sanitized_failure(self):
        with tempfile.TemporaryDirectory() as work:
            work = Path(work)
            vault = work / "fixture.yaml"
            vault.write_text(yaml.safe_dump({"sing_box_secrets": self.secrets}))
            # Fake only the decryption executable, never access a live Vault/password.
            executable = work / "ansible-vault"
            executable.write_text(f"#!{sys.executable}\nimport pathlib, sys\nsys.stdout.write(pathlib.Path(sys.argv[-1]).read_text())\n")
            executable.chmod(0o700)
            config = work / "config.yaml"
            config.write_bytes((STACK / "config.yaml").read_bytes())
            before = config.read_bytes()
            command = [sys.executable, str(STACK / "prefill-servers.py"),
                       "--vault-file", str(vault), "--config", str(config), "--node", "dyn2"]
            env = {**os.environ, "PATH": str(work) + os.pathsep + os.environ["PATH"]}
            result = subprocess.run(command, env=env, text=True, capture_output=True, check=True)
            self.assertEqual(config.read_bytes(), before)
            servers = yaml.safe_load(result.stdout)["servers"]
            self.assertEqual([s["name"] for s in servers], ["dyn2"])
            result = subprocess.run([*command, "--write"], env=env, text=True, capture_output=True, check=True)
            self.assertEqual(yaml.safe_load(config.read_text())["servers"], servers)
            self.assertNotIn("fixture-secret", result.stdout + result.stderr + config.read_text())
            before = config.read_bytes()
            vault.write_text("sing_box_secrets: [fixture-secret")
            result = subprocess.run([*command, "--write"], env=env, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("fixture-secret", result.stdout + result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(config.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
