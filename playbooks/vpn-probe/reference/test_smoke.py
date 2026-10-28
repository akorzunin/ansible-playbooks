"""Finite readiness evidence tests with fake HTTPS/UDP; never open sockets."""
import contextlib
import hashlib
import hmac
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import endpoint
import smoke


class SmokeTests(unittest.TestCase):
    def run_smoke(self, receipt_complete=True, udp_timeout=False):
        data = b"".join(endpoint.blocks(4096))
        config = {"bind_ipv4": "192.0.2.1", "token": "a" * 64, "receipt_token": "b" * 64,
                  "run": "offline-smoke", "objects": {"fresh": {"sha256": hashlib.sha256(data).hexdigest()}}}
        session = {"session": "c" * 32, "key": "d" * 64}
        bodies = [b"", data, b"", json.dumps({"body_bytes_sent": 4096, "source": "192.0.2.1",
                  "outcome": "complete" if receipt_complete else "active"}).encode(),
                  json.dumps(session).encode(), json.dumps({"received": 1, "sent": 1, "source": "192.0.2.1"}).encode()]
        statuses = [401, 200, 409, 200, 200, 200]
        replies = [SimpleNamespace(status=status, read=lambda _, body=body: body, getheader=lambda _: None)
                   for status, body in zip(statuses, bodies)]
        connection, udp = MagicMock(), MagicMock()
        connection.getresponse.side_effect = replies
        def echo(_):
            if udp_timeout:
                raise TimeoutError("private detail must not be reported")
            packet = udp.send.call_args.args[0]
            body = b"VRR1" + packet[4:-32]
            return body + hmac.digest(bytes.fromhex(session["key"]), body, "sha256")
        udp.recv.side_effect = echo
        self.evidence = {"readiness": "failed", "stage": "input", "https_operations": 0, "udp_packets": 0, "http": []}
        self.connection, self.udp = connection, udp
        with patch.object(smoke.os, "geteuid", return_value=1234), \
                patch.dict(smoke.os.environ, {"CREDENTIALS_DIRECTORY": "/unused"}), \
                patch.object(smoke.Path, "read_text", return_value=json.dumps(config)), \
                patch.object(smoke.ssl, "create_default_context"), \
                patch.object(smoke.http.client, "HTTPSConnection") as https, \
                patch.object(smoke.socket, "socket") as socket:
            https.return_value = connection
            socket.return_value.__enter__.return_value = udp
            smoke.main(self.evidence)

    def test_six_https_one_udp_and_redacted_receipts(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.run_smoke()
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(self.evidence["readiness"], "passed")
        self.assertEqual(self.evidence["https_operations"], 6)
        self.assertEqual(self.evidence["udp_packets"], 1)
        self.assertEqual(self.connection.request.call_count, 6)
        self.assertEqual(self.connection.close.call_count, 6)
        self.udp.send.assert_called_once()
        self.assertEqual(self.evidence["object_receipt"], {"bytes": 4096, "complete": True, "source_matches_bind": True})
        self.assertEqual(self.evidence["udp_receipt"], {"received": 1, "sent": 1, "source_matches_bind": True})
        serialized = json.dumps(self.evidence)
        for private in ("a" * 64, "b" * 64, "c" * 32, "d" * 64, "192.0.2.1"):
            self.assertNotIn(private, serialized)

    def test_real_https_connection_reaches_mock_connect_and_closes_on_failure(self):
        evidence = {"readiness": "failed", "stage": "input", "https_operations": 0, "udp_packets": 0, "http": []}
        config = {"bind_ipv4": "192.0.2.1", "token": "a" * 64, "run": "offline"}
        tls = smoke.ssl.create_default_context()
        with patch.object(smoke.os, "geteuid", return_value=1234), \
                patch.dict(smoke.os.environ, {"CREDENTIALS_DIRECTORY": "/unused"}), \
                patch.object(smoke.Path, "read_text", return_value=json.dumps(config)), \
                patch.object(smoke.ssl, "create_default_context", return_value=tls), \
                patch.object(smoke.http.client.HTTPSConnection, "connect", side_effect=ConnectionAbortedError("offline")) as connect, \
                patch.object(smoke.http.client.HTTPSConnection, "close") as close:
            with self.assertRaises(ConnectionAbortedError):
                smoke.main(evidence)
        connect.assert_called_once()
        close.assert_called_once()
        self.assertEqual(evidence["stage"], "bad-bearer")

    def test_active_receipt_fails_without_retry_or_relaxed_assertion(self):
        with self.assertRaises(AssertionError):
            self.run_smoke(receipt_complete=False)
        self.assertEqual(self.evidence["stage"], "object-receipt")
        self.assertFalse(self.evidence["object_receipt"]["complete"])
        self.assertEqual(self.connection.request.call_count, 4)
        self.udp.send.assert_not_called()

    def test_udp_timeout_retains_stage_and_partial_counts(self):
        with self.assertRaises(TimeoutError):
            self.run_smoke(udp_timeout=True)
        self.assertEqual(self.evidence["stage"], "udp-echo")
        self.assertEqual(self.evidence["https_operations"], 5)
        self.assertEqual(self.evidence["udp_packets"], 1)
        self.assertNotIn("private detail", json.dumps(self.evidence))


if __name__ == "__main__":
    unittest.main()
