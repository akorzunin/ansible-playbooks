#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import generate

spec = importlib.util.spec_from_file_location("updater", Path(__file__).with_name("update-linux.py"))
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.connections = {kind: {"type": kind, "tag": kind} for kind in ("vless", "naive", "ssh")}
        self.tokens = {platform: str(i) * 64 for i, platform in enumerate(generate.ORDERS)}

    def test_platforms_keep_inbounds_and_use_auto_and_vless_udp(self):
        for platform, order in generate.ORDERS.items():
            with self.subTest(platform=platform):
                base = json.loads((generate.ROOT / "templates" / f"{platform}.json").read_text())
                original = json.loads(json.dumps(base))
                result = generate.make_profile(base, self.connections, order)
                self.assertEqual(base, original)
                self.assertEqual(result["inbounds"], base["inbounds"])
                self.assertEqual(result["outbounds"][0]["default"], "auto")
                self.assertEqual(result["outbounds"][1]["outbounds"], order)
                self.assertEqual(result["route"]["final"], "proxy")
                rules = result["route"]["rules"]
                self.assertEqual(rules[0], {"action": "sniff"})
                self.assertEqual(rules[1], {
                    "domain_suffix": ["duckdns.org"], "action": "route", "outbound": "direct",
                })
                udp = next(r for r in rules if r.get("network") == "udp")
                self.assertGreater(rules.index(udp), 1)
                self.assertEqual(udp["outbound"], "vless")
                self.assertNotIn("cache_file", result["experimental"])
                for inbound in result["inbounds"]:
                    if inbound["type"] == "tun":
                        self.assertNotIn("stack", inbound)
                for rule_set in result["route"]["rule_set"]:
                    if rule_set["type"] == "remote":
                        self.assertNotIn("download_detour", rule_set)
                        self.assertEqual(rule_set["http_client"], {"engine": "go"})
                if platform == "android":
                    self.assertEqual([i["type"] for i in result["inbounds"]], ["tun"])
                if platform == "linux":
                    self.assertNotIn("auto_detect_interface", result["route"])

    def test_tokens_stay_stable_and_artifacts_are_private(self):
        with tempfile.TemporaryDirectory() as work:
            output, fresh = Path(work) / "output", Path(work) / "fresh"
            with patch.object(generate.subprocess, "run"):
                generate.generate(output, self.connections, self.tokens)
                tokens = (output / "tokens.json").read_bytes()
                urls = (output / "urls.json").read_bytes()
                generate.generate(output, self.connections, self.tokens)
                generate.generate(fresh, self.connections, self.tokens)
            self.assertEqual(tokens, (output / "tokens.json").read_bytes())
            self.assertEqual(urls, (output / "urls.json").read_bytes())
            self.assertEqual(urls, (fresh / "urls.json").read_bytes())
            self.assertEqual(json.loads(tokens), self.tokens)
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)
            for artifact in output.iterdir():
                self.assertEqual(artifact.stat().st_mode & 0o777, 0o600)

    def test_failed_validation_does_not_replace_published_profiles(self):
        with tempfile.TemporaryDirectory() as work:
            output = Path(work) / "output"
            with patch.object(generate.subprocess, "run"):
                generate.generate(output, self.connections, self.tokens)
            before = {p.name: p.read_bytes() for p in output.iterdir()}
            self.connections["naive"]["password"] = "changed"
            with patch.object(generate.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "check")):
                with self.assertRaises(subprocess.CalledProcessError):
                    generate.generate(output, self.connections, self.tokens)
            self.assertEqual(before, {p.name: p.read_bytes() for p in output.iterdir()})

    def test_missing_or_invalid_tokens_do_not_replace_artifacts(self):
        with tempfile.TemporaryDirectory() as work:
            output = Path(work) / "output"
            with patch.object(generate.subprocess, "run"):
                generate.generate(output, self.connections, self.tokens)
            before = {p.name: p.read_bytes() for p in output.iterdir()}
            for tokens in ({}, {**self.tokens, "linux": "invalid"}):
                with self.subTest(tokens=tokens), patch.object(generate.subprocess, "run") as check:
                    with self.assertRaises(ValueError):
                        generate.generate(output, self.connections, tokens)
                    check.assert_not_called()
                    self.assertEqual(before, {p.name: p.read_bytes() for p in output.iterdir()})

    def test_invalid_connections_are_rejected(self):
        with tempfile.TemporaryDirectory() as work:
            for connections in (
                {},
                {**self.connections, "ssh": {"type": "direct", "tag": "ssh"}},
                {**self.connections, "ssh": {"type": "ssh", "tag": "naive"}},
                {**self.connections, "ssh": {"type": "ssh", "tag": "proxy"}},
            ):
                with self.subTest(connections=connections), patch.object(generate.subprocess, "run") as check:
                    with self.assertRaises(ValueError):
                        generate.generate(Path(work), connections, self.tokens)
                    check.assert_not_called()


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.target = Path(self.work.name) / "config.json"
        self.old = b'{"outbounds": [{"type": "direct"}], "route": {"final": "direct"}}'
        self.new = b'{"outbounds": [{"type": "direct"}], "route": {"final": "proxy"}}'
        self.target.write_bytes(self.old)
        self.target.chmod(0o640)
        self.url_file = Path(self.work.name) / "enrollment.json"
        self.url_file.write_text('{"url": "https://example.com/private/config.json"}')

    def test_unchanged_config_does_not_restart(self):
        with patch.object(updater, "download", return_value=self.old), patch.object(updater, "restart") as restart:
            self.assertFalse(updater.update(self.url_file, self.target))
            restart.assert_not_called()

    def test_network_failure_keeps_installed_config(self):
        with patch.object(updater, "download", side_effect=OSError("offline")):
            with self.assertRaises(OSError):
                updater.update(self.url_file, self.target)
        self.assertEqual(self.target.read_bytes(), self.old)

    def test_invalid_config_keeps_installed_config(self):
        with patch.object(updater, "download", return_value=self.new), patch.object(
            updater.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "check")
        ), patch.object(updater, "restart") as restart:
            with self.assertRaises(subprocess.CalledProcessError):
                updater.update(self.url_file, self.target)
            restart.assert_not_called()
        self.assertEqual(self.target.read_bytes(), self.old)

    def test_success_preserves_file_permissions(self):
        with patch.object(updater, "download", return_value=self.new), patch.object(updater.subprocess, "run"), patch.object(updater, "restart"):
            self.assertTrue(updater.update(self.url_file, self.target))
        self.assertEqual(self.target.read_bytes(), self.new)
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o640)

    def test_failed_restart_rolls_back(self):
        with patch.object(updater, "download", return_value=self.new), patch.object(updater.subprocess, "run"), patch.object(
            updater, "restart", side_effect=[RuntimeError("startup failed"), None]
        ) as restart:
            with self.assertRaises(RuntimeError):
                updater.update(self.url_file, self.target)
            self.assertEqual(restart.call_count, 2)
        self.assertEqual(self.target.read_bytes(), self.old)

    def test_reject_plain_http_and_redirects(self):
        with self.assertRaises(ValueError):
            updater.download("http://example.com/private/config.json")
        with self.assertRaises(ValueError):
            updater.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example.com/")


if __name__ == "__main__":
    unittest.main()
