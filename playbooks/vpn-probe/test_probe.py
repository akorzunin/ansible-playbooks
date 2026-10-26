import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("probe", Path(__file__).with_name("probe.py"))
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class ProbeTests(unittest.TestCase):
    def test_only_explicit_loopback_proxies(self):
        self.assertEqual(probe.proxy_argument("cherry=socks5h://127.0.0.1:12345"),
                         ("cherry", "socks5h://127.0.0.1:12345"))
        for value in ("name=http://example.com:80", "name=http://user:password@127.0.0.1:80",
                      "name=socks5://127.0.0.1:80", "name=http://127.0.0.1:no", "invalid"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                probe.proxy_argument(value)

    def test_controls_must_be_https_without_credentials(self):
        self.assertEqual(probe.https_argument("https://example.com/"), "https://example.com/")
        for value in ("http://example.com", "https://user:password@example.com", "https://"):
            with self.assertRaises(argparse.ArgumentTypeError):
                probe.https_argument(value)

    def test_direct_failures_never_accumulate_endpoint_failure(self):
        for controls in ([{"ok": False}, {"ok": False}], [{"ok": True}, {"ok": False}]):
            self.assertEqual(probe.classify(controls, [{"ok": False}], 9, 3),
                             ("inconclusive_direct_controls", 0))

    def test_persistent_proxy_failure_is_only_a_suspicion(self):
        controls = [{"ok": True}, {"ok": True}]
        checks = [{"ok": False}, {"ok": False}]
        self.assertEqual(probe.classify(controls, checks, 0, 3), ("failing", 1))
        self.assertEqual(probe.classify(controls, checks, 2, 3), ("suspected_path_failure", 3))

    def test_recovery_resets_streak(self):
        self.assertEqual(probe.classify([{"ok": True}], [{"ok": True}], 5, 3), ("healthy", 0))

    def test_single_destination_failure_does_not_suggest_reallocation(self):
        self.assertEqual(probe.classify([{"ok": True}], [{"ok": True}, {"ok": False}], 5, 3),
                         ("degraded_destination_or_path", 0))

    def test_atomic_metrics_snapshot_replaces_old_values_and_tracks_freshness(self):
        row = {
            "time": "2026-01-01T00:00:00+00:00",
            "controls": [{"ok": True}, {"ok": True}],
            "proxies": {name: {"checks": {target: {"ok": True} for target in ("gstatic", "cloudflare")}}
                        for name in ("ssh", "naive", "vless")},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metrics.prom"
            probe.write_metrics(path, row)
            healthy = path.read_text()
            self.assertIn("vpn_probe_timestamp_seconds 1767225600.0", healthy)
            self.assertIn("vpn_probe_controls_ok 1", healthy)
            self.assertEqual(healthy.count('vpn_probe_success{'), 6)
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)
            row["controls"][0]["ok"] = False
            row["proxies"]["ssh"]["checks"]["gstatic"]["ok"] = False
            probe.write_metrics(path, row)
            self.assertIn("vpn_probe_controls_ok 0", path.read_text())
            self.assertIn('vpn_probe_success{protocol="ssh",target="gstatic"} 0', path.read_text())
            self.assertFalse(path.with_suffix(".tmp").exists())

    def test_metrics_only_cli_does_not_require_unbounded_jsonl_log(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metrics.prom"
            with patch("sys.argv", ["probe.py", "--proxy", "ssh=socks5h://127.0.0.1:22340",
                                    "--control-url", "https://example.com", "--control-url", "https://example.org",
                                    "--metrics-output", str(path)]), patch.object(probe, "request", return_value={"ok": True}), patch("builtins.print"):
                probe.main()
            self.assertIn("vpn_probe_controls_ok 1", path.read_text())
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_continuous_mode_collects_more_than_one_round(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metrics.prom"
            with patch("sys.argv", ["probe.py", "--proxy", "ssh=socks5h://127.0.0.1:22340",
                                    "--control-url", "https://example.com", "--control-url", "https://example.org",
                                    "--metrics-output", str(path), "--continuous", "--interval", "60"]), \
                    patch.object(probe, "request", return_value={"ok": True}) as request, \
                    patch.object(probe.time, "sleep", side_effect=[None, None, RuntimeError("stop")]), \
                    patch.object(probe, "write_metrics", wraps=probe.write_metrics) as metrics, \
                    patch("builtins.print"), self.assertRaisesRegex(RuntimeError, "stop"):
                probe.main()
            self.assertEqual(metrics.call_count, 2)
            self.assertEqual(request.call_count, 8)
            self.assertTrue(path.exists())

    @patch.object(probe.subprocess, "run")
    def test_direct_curl_ignores_environment_and_curlrc(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, json.dumps({"http_code": 200, "time_total": .1}), "")
        with patch.dict(os.environ, {"HTTPS_PROXY": "http://bad:80", "all_proxy": "http://bad:80"}):
            self.assertTrue(probe.request("https://example.com")["ok"])
        args, kwargs = run.call_args
        command = args[0]
        self.assertEqual(command[:2], ["curl", "--disable"])
        self.assertEqual(command[command.index("--proxy") + 1], "")
        self.assertEqual(command[command.index("--noproxy") + 1], "*")
        self.assertNotIn("HTTPS_PROXY", kwargs["env"])
        self.assertNotIn("all_proxy", kwargs["env"])

    @patch.object(probe.subprocess, "run")
    def test_proxy_is_explicit_and_expected_status_is_checked(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, '{"http_code": 403}', "")
        self.assertFalse(probe.request("https://example.com", "http://127.0.0.1:80", 204)["ok"])
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--proxy") + 1], "http://127.0.0.1:80")
        self.assertEqual(command[command.index("--noproxy") + 1], "")

    @patch.object(probe.subprocess, "run")
    def test_timeouts_and_malformed_output_are_failures(self, run):
        for result in (subprocess.TimeoutExpired("curl", 15), OSError("missing curl")):
            run.side_effect = result
            self.assertFalse(probe.request("https://example.com")["ok"])
        run.side_effect = None
        for output in ("not json", "null", "[]", '{"http_code": "invalid"}'):
            run.return_value = subprocess.CompletedProcess([], 1, output, "private diagnostic")
            self.assertEqual(probe.request("https://example.com"),
                             {"ok": False, "exit": None, "http_status": 0, "seconds": None})


if __name__ == "__main__":
    unittest.main()
