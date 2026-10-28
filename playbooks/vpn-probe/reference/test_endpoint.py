"""Offline only: fake sockets/clocks, isolated keys and in-memory TLS handshake."""
import hashlib
import hmac
import io
import json
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zlib

import endpoint
import firewall
import prepare


class Clock:
    def __init__(self):
        self.value = 1000.0

    def __call__(self):
        return self.value


def config():
    return {"schema_version": 1, "bind_ipv4": "192.0.2.1", "sources": ["192.0.2.1/32", "198.51.100.1/32"],
            "run": "offline-test", "expires": 1900, "token": "a" * 64, "receipt_token": "b" * 64,
            "objects": {name: {"object_bytes": size, "sha256": "c" * 64} for name, size in endpoint.OBJECTS.items()}}


class FakeSocket:
    def __init__(self, data=b""):
        self.data, self.output = data, b""

    def makefile(self, _):
        return io.BytesIO(self.data)

    def sendall(self, data):
        self.output += data

    def settimeout(self, _):
        pass


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.lease = endpoint.Lease(config(), clock=self.clock, wall=self.clock)

    def headers(self, request="req1", receipt=False):
        return {"authorization": "Bearer " + ("b" if receipt else "a") * 64,
                "x-run-id": "offline-test", "x-request-id": request}

    def call(self, path, request="req1", method="GET", receipt=False, headers=None):
        headers = self.headers(request, receipt) if headers is None else headers
        data = (f"{method} {path} HTTP/1.1\r\nHost: reference\r\n" +
                "".join(f"{key}: {value}\r\n" for key, value in headers.items()) + "\r\n").encode()
        sock = FakeSocket(data)
        handler = object.__new__(endpoint.Handler)
        handler.server = SimpleNamespace(lease=self.lease)
        handler.client_address = ("198.51.100.1", 32123)
        with patch.object(endpoint.time, "sleep"):
            handler.serve(sock)
        header, body = sock.output.split(b"\r\n\r\n", 1)
        return int(header.split()[1]), header, body

    def test_valid_config_and_strict_expiry(self):
        self.assertEqual(endpoint.validate(config(), now=1000), config())
        for expires in (1000, 999, 1901):
            with self.assertRaises(ValueError):
                endpoint.validate(config() | {"expires": expires}, now=1000)
        for changes in ({"unknown": 1}, {"sources": ["0.0.0.0/0"]},
                        {"bind_ipv4": "0.0.0.0"}, {"receipt_token": "a" * 64},
                        {"sources": ["198.51.100.0/24"]}):
            with self.assertRaises(ValueError):
                endpoint.validate(config() | changes, now=1000)

    def test_object_generation_finite_reproducible_and_noncompressible(self):
        data = b"".join(endpoint.blocks(262144))
        self.assertEqual(data, b"".join(endpoint.blocks(262144)))
        self.assertNotEqual(data[:65536], data[65536:131072])
        self.assertEqual(len(b"".join(endpoint.blocks(65537))), 65537)
        self.assertGreater(len(zlib.compress(data)) / len(data), 0.99)
        self.assertGreater(endpoint.OBJECTS["continuous"], 3221225472)
        self.assertLessEqual(max(map(len, endpoint.blocks(262144))), 65536)

    def test_manifest_streaming_hash(self):
        with patch.object(endpoint, "OBJECTS", {"fresh": 101}):
            result = endpoint.object_manifest()
        self.assertEqual(result["fresh"], {"object_bytes": 101,
                         "sha256": hashlib.sha256(next(endpoint.blocks(101))).hexdigest()})

    def test_unauthorized_wrong_run_unlisted_source_and_expired(self):
        for headers, source, expected in (({}, "198.51.100.1", 401),
                (self.headers() | {"x-run-id": "wrong"}, "198.51.100.1", 400),
                (self.headers(), "203.0.113.2", 403)):
            with self.assertRaises(endpoint.Rejected) as caught:
                self.lease.authorize(headers, source)
            self.assertEqual(caught.exception.status, expected)
        self.clock.value = 1900
        with self.assertRaises(endpoint.Rejected) as caught:
            self.lease.authorize(self.headers(), "198.51.100.1")
        self.assertEqual(caught.exception.status, 403)

    def test_replay_and_request_limit(self):
        self.lease.authorize(self.headers(), "198.51.100.1")
        with self.assertRaises(endpoint.Rejected) as caught:
            self.lease.authorize(self.headers(), "198.51.100.1")
        self.assertEqual(caught.exception.status, 409)
        with patch.object(endpoint, "MAX_REQUESTS", 1):
            with self.assertRaises(endpoint.Rejected) as caught:
                self.lease.authorize(self.headers("new"), "198.51.100.1")
        self.assertEqual(caught.exception.status, 429)

    def test_receipt_separate_token_and_observed_source_not_forwarded(self):
        status, headers, body = self.call("/objects/fresh", headers=self.headers() | {"x-forwarded-for": "forged"})
        self.assertEqual(status, 200)
        self.assertIn(b"Cache-Control: no-store, no-transform", headers)
        self.assertNotIn(b"Content-Encoding", headers)
        self.assertEqual(len(body), 4096)
        self.assertEqual(self.call("/receipts/req1", "read1")[0], 401)
        status, _, body = self.call("/receipts/req1", "read2", receipt=True)
        receipt = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(receipt["source"], "198.51.100.1")
        self.assertEqual(receipt["body_bytes_sent"], 4096)
        self.assertEqual(receipt["outcome"], "complete")
        self.assertNotIn("a" * 64, body.decode())
        self.assertEqual(self.call("/objects/fresh")[0], 409)

    def test_no_proxy_redirect_ranges_bodies_or_duplicate_headers(self):
        self.assertEqual(self.call("http://example.invalid/", "r1")[0], 404)
        self.assertEqual(self.call("/objects/fresh?query=1", "r2")[0], 404)
        for headers in ({"range": "bytes=1-2"}, {"content-length": "1"}, {"transfer-encoding": "chunked"}):
            self.assertEqual(self.call("/objects/fresh", headers=self.headers() | headers)[0], 400)
        for wire in (b"GET / HTTP/1.1\r\nHost: x\r\nHost: y\r\n\r\n",
                     b"GET / HTTP/1.1\r\nHost: x\r\nX: " + b"a" * 8192 + b"\r\n\r\n"):
            with self.assertRaises(endpoint.Rejected):
                endpoint.read_request(io.BytesIO(wire))

    def test_concurrency_budget_and_pacing(self):
        self.lease.active = 4
        self.assertEqual(self.call("/objects/fresh")[0], 429)
        self.lease.active = 0
        self.lease.budget = 4095
        status, _, body = self.call("/objects/fresh", "r2")
        self.assertEqual(status, 200)  # Headers declared object; body fails closed.
        self.assertEqual(body, b"")
        self.assertEqual(self.lease.receipts["r2"]["outcome"], "budget-or-expiry")
        self.lease.budget = 10000000
        self.assertEqual(self.lease.reserve(endpoint.RATE), 0)
        self.assertAlmostEqual(self.lease.reserve(1), 1)

    def test_disconnect_preserves_partial_receipt_and_slot(self):
        handler = object.__new__(endpoint.Handler)
        handler.server = SimpleNamespace(lease=self.lease)
        handler.client_address = ("198.51.100.1", 1)
        sock = FakeSocket()
        sock.sendall = unittest.mock.Mock(side_effect=[None, OSError()])
        with self.assertRaises(OSError), patch.object(endpoint.time, "sleep"):
            handler.object(sock, "fresh", "partial", 1000)
        self.assertEqual(self.lease.active, 0)
        self.assertEqual(self.lease.receipts["partial"]["outcome"], "interrupted")

    def session_packet(self, session, seq=0, magic=b"VRU1"):
        data = endpoint.PACKET.pack(magic, bytes.fromhex(session["session"]), seq, 42.0, b"p" * 32, b"\0" * 32)
        return data[:-32] + hmac.digest(bytes.fromhex(session["key"]), data[:-32], "sha256")

    def test_udp_authenticated_fixed_size_reply_replay_and_counters(self):
        session = self.lease.new_session("198.51.100.1")
        sent = []
        peer = ("198.51.100.1", 1111)
        send = lambda data, address: sent.append((data, address))
        packet = self.session_packet(session, 2)
        self.lease.udp(packet, peer, send)
        self.lease.udp(packet, peer, send)
        self.clock.value += 0.1
        self.lease.udp(self.session_packet(session, 0), peer, send)
        stats = self.lease.udp_receipt(session["session"])
        self.assertEqual((stats["received"], stats["sent"], stats["duplicates"], stats["reordered"]), (2, 2, 1, 1))
        self.assertEqual(bytes.fromhex(stats["seen_bitmap_hex"])[0], 5)
        reply = sent[0][0]
        self.assertEqual(len(reply), len(packet))
        self.assertEqual(reply[:4], b"VRR1")
        self.assertTrue(hmac.compare_digest(reply[-32:], hmac.digest(bytes.fromhex(session["key"]), reply[:-32], "sha256")))

    def test_udp_wrong_key_source_port_size_sequence_magic_and_expiry(self):
        session = self.lease.new_session("198.51.100.1")
        send = unittest.mock.Mock()
        packet = self.session_packet(session)
        for data, peer in ((packet[:-1], ("198.51.100.1", 1)),
                           (packet + b"a", ("198.51.100.1", 1)),
                           (packet[:-32] + b"z" * 32, ("198.51.100.1", 1)),
                           (packet, ("192.0.2.1", 1)),
                           (self.session_packet(session, 30000), ("198.51.100.1", 1)),
                           (self.session_packet(session, magic=b"VRR1"), ("198.51.100.1", 1))):
            self.lease.udp(data, peer, send)
        send.assert_not_called()
        self.lease.udp(packet, ("198.51.100.1", 1), send)
        self.clock.value += 0.1
        self.lease.udp(self.session_packet(session, 1), ("198.51.100.1", 2), send)
        self.assertEqual(send.call_count, 1)
        self.clock.value = 1600
        self.lease.udp(self.session_packet(session, 1), ("198.51.100.1", 1), send)
        self.assertEqual(send.call_count, 1)

    def test_udp_session_limit_and_rate(self):
        sessions = [self.lease.new_session("198.51.100.1") for _ in range(4)]
        with self.assertRaises(endpoint.Rejected) as caught:
            self.lease.new_session("198.51.100.1")
        self.assertEqual(caught.exception.status, 429)
        send = unittest.mock.Mock()
        for seq in range(11):
            self.lease.udp(self.session_packet(sessions[0], seq), ("198.51.100.1", 1), send)
        self.assertEqual(send.call_count, 10)
        self.assertEqual(self.lease.udp_receipt(sessions[0]["session"])["rate_drops"], 1)
        self.clock.value += 0.02
        self.lease.udp(self.session_packet(sessions[0], 10), ("198.51.100.1", 1), send)
        self.assertEqual(send.call_count, 11)

    def test_http_admission_bounds_even_unauthenticated_connections(self):
        server = object.__new__(endpoint.Server)
        server.lease = self.lease
        server.connections = server.window_count = 0
        server.window = self.clock()
        self.assertFalse(server.admit("203.0.113.1"))
        for _ in range(32):
            self.assertTrue(server.admit("198.51.100.1"))
        self.assertFalse(server.admit("198.51.100.1"))
        self.clock.value += 1
        self.assertTrue(server.admit("198.51.100.1"))
        server.connections = 2048
        self.clock.value += 1
        self.assertFalse(server.admit("198.51.100.1"))

    def test_spent_marker_blocks_restart_before_sockets(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "spent").touch()
            with patch.object(endpoint, "validate"), patch.object(endpoint.os, "geteuid", return_value=1234):
                with self.assertRaises(FileExistsError):
                    endpoint.run(config(), "unused", "unused", directory)

    def test_private_inputs_refuse_world_readable_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text("{}")
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                endpoint.private_json(path)
            path.chmod(0o600)
            self.assertEqual(endpoint.private_json(path), {})
            link = Path(directory) / "link"
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                endpoint.private_json(link)

    def test_systemd_readonly_root_owned_group_credential(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "config.json"
            path.write_text("{}")
            original_stat = Path.stat
            info = SimpleNamespace(st_uid=0, st_gid=endpoint.os.getegid(), st_mode=0o100440, st_size=2)
            def credential_stat(candidate, *args, **kwargs):
                return info if candidate == path else original_stat(candidate, *args, **kwargs)
            with patch.dict(endpoint.os.environ, {"CREDENTIALS_DIRECTORY": directory}), \
                    patch.object(endpoint.os, "statvfs", return_value=SimpleNamespace(f_flag=endpoint.os.ST_RDONLY)), \
                    patch.object(Path, "stat", credential_stat):
                self.assertEqual(endpoint.credential_json(path), {})
                info.st_gid = 0  # systemd can instead grant the dynamic UID a read ACL.
                self.assertEqual(endpoint.credential_json(path), {})
                info.st_gid = endpoint.os.getegid()
                for field, value in (("st_mode", 0o100444), ("st_mode", 0o100460),
                                     ("st_gid", info.st_gid + 1), ("st_uid", 12345), ("st_size", 16385)):
                    previous = getattr(info, field)
                    setattr(info, field, value)
                    with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                        endpoint.credential_json(path)
                    setattr(info, field, previous)

    def test_systemd_credential_rejects_writable_mount_wrong_path_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "config.json"
            path.write_text("{}")
            path.chmod(0o440)
            with self.assertRaises(ValueError):
                endpoint.private_json(path)  # Controller inputs remain owner-only.
            with patch.dict(endpoint.os.environ, {"CREDENTIALS_DIRECTORY": directory}):
                with patch.object(endpoint.os, "statvfs", return_value=SimpleNamespace(f_flag=0)), self.assertRaises(ValueError):
                    endpoint.credential_json(path)
                with self.assertRaises(ValueError):
                    endpoint.credential_json(root / "different.json")
                path.unlink()
                path.symlink_to(root / "different.json")
                with self.assertRaises(ValueError):
                    endpoint.credential_json(path)

    def test_firewall_host_sources_render_as_literals_not_prefix_elements(self):
        script = firewall.rules(config()["sources"], False)
        self.assertIn("set sources { type ipv4_addr; elements = { 192.0.2.1, 198.51.100.1 }; }", script)
        self.assertNotIn("/32", script)
        self.assertNotIn("flags interval", script)

    def test_firewall_atomic_own_table_only_and_no_wildcard_accept(self):
        script = firewall.rules(config()["sources"], True)
        self.assertTrue(script.startswith("delete table inet vpn_reference\n"))
        self.assertNotIn("flush ruleset", script)
        self.assertNotIn(" accept", script.replace("policy accept", ""))
        self.assertIn("tcp dport 9443 counter drop", script)
        self.assertIn("udp dport 9444 counter drop", script)
        self.assertNotIn("443;", script)
        with self.assertRaises(ValueError):
            firewall.rules(["0.0.0.0/0"], False)


@unittest.skipUnless(shutil.which("openssl"), "openssl unavailable")
class PreparationTests(unittest.TestCase):
    def test_private_preparation_tls_trust_ip_and_no_key_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lease"
            objects = config()["objects"]
            with patch.object(endpoint, "object_manifest", return_value=objects), patch.object(prepare.time, "time", return_value=1800000000):
                prepare.prepare(root, {key: config()[key] for key in ("bind_ipv4", "sources", "run")})
            server_config = json.loads((root / "config.json").read_text())
            self.assertEqual(server_config["expires"], 1800000900)
            for name in endpoint.OBJECTS:
                with self.subTest(descriptor=name):
                    descriptor = json.loads((root / f"{name}.json").read_text())
                    self.assertEqual(descriptor["expires_at"], server_config["expires"])
                    self.assertIs(type(descriptor["expires_at"]), int)
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            for path in root.iterdir():
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertFalse((root / "ca.key").exists())
            descriptor = json.loads((root / "continuous.json").read_text())
            self.assertEqual(descriptor["object_bytes"], 4294967296)
            self.assertEqual(descriptor["ca_file"], str(root / "ca.pem"))
            result = subprocess.run(["openssl", "verify", "-CAfile", str(root / "ca.pem"),
                                     "-verify_ip", "192.0.2.2", str(root / "cert.pem")], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.handshake(root, trusted=True)
            with self.assertRaises(ssl.SSLCertVerificationError):
                self.handshake(root, trusted=False)
            with self.assertRaises(FileExistsError), patch.object(endpoint, "object_manifest", return_value=objects):
                prepare.prepare(root, {key: config()[key] for key in ("bind_ipv4", "sources", "run")})

    def handshake(self, root, trusted):
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(root / "cert.pem", root / "key.pem")
        client_context = ssl.create_default_context(cafile=root / "ca.pem" if trusted else None)
        ci, co, si, so = (ssl.MemoryBIO() for _ in range(4))
        client = client_context.wrap_bio(ci, co, server_hostname="192.0.2.1")
        server = server_context.wrap_bio(si, so, server_side=True)
        complete = set()
        for _ in range(12):
            for alias, connection in (("client", client), ("server", server)):
                try:
                    connection.do_handshake()
                    complete.add(alias)
                except ssl.SSLWantReadError:
                    pass
            si.write(co.read())
            ci.write(so.read())
            if len(complete) == 2:
                return
        self.fail("in-memory TLS handshake did not complete")


if __name__ == "__main__":
    unittest.main()
