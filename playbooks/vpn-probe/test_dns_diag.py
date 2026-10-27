import copy
import importlib.util
import json
from pathlib import Path
import socket
import ssl
import struct
import subprocess
import unittest
from unittest.mock import MagicMock, patch

SPEC = importlib.util.spec_from_file_location("dns_diag", Path(__file__).with_name("dns_diag.py"))
dns = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dns)

PLAN = {
    "resolver": {"alias": "resolver-one", "ipv4": "1.1.1.1", "tls_name": "cloudflare-dns.com", "doh_path": "/dns-query"},
    "names": [{"alias": "youtube", "name": "youtube.com", "expect": "positive"},
              {"alias": "positive", "name": "example.com", "expect": "positive"},
              {"alias": "negative", "name": "vpn-dns-control.invalid", "expect": "nxdomain"}],
    "edns": False,
}


def response(request, flags=0x8180, records=(), authority=()):
    _, end = dns.dns_name(request, 12)
    return (request[:2] + struct.pack("!5H", flags, 1, len(records), len(authority), 0)
            + request[12:end + 4] + b"".join(records) + b"".join(authority))


def rr(kind, data, owner=b"\xc0\x0c"):
    return owner + struct.pack("!HHIH", kind, 1, 300, len(data)) + data


class DnsTests(unittest.TestCase):
    def test_plan_and_private_bootstrap(self):
        self.assertEqual(dns.validate_plan(copy.deepcopy(PLAN)), PLAN)
        for key, value in (("ipv4", "not-an-ip"), ("tls_name", "https://bad"), ("doh_path", "/redirect")):
            plan = copy.deepcopy(PLAN)
            plan["resolver"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                dns.validate_plan(plan)
        plan = copy.deepcopy(PLAN)
        plan["fallback"] = True
        with self.assertRaises(ValueError):
            dns.validate_plan(plan)

    def test_queries_differ_only_in_id_when_same_options(self):
        with patch.object(dns.secrets, "randbelow", return_value=123):
            self.assertEqual(dns.query("youtube.com", "A"), dns.query("youtube.com", "A"))
        for edns in (False, True):
            q = dns.query("youtube.com", "AAAA", edns)
            self.assertEqual(struct.unpack_from("!6H", q)[1:], (0x100, 1, 0, 0, int(edns)))

    def test_answers_and_flags(self):
        for qtype, address in (("A", "8.8.8.8"), ("AAAA", "2001:4860:4860::8888")):
            q = dns.query("youtube.com", qtype)
            r = response(q, flags=0x81A0, records=[rr(dns.TYPES[qtype], dns.ipaddress.ip_address(address).packed)])
            parsed = dns.decode(r, q)
            self.assertEqual(parsed["answer"][0]["address"], address)
            self.assertEqual(parsed["answer"][0]["ttl"], 300)
            self.assertTrue(parsed["ad"])
            self.assertEqual(dns.usability(parsed, "positive"), "usable-answer")

    def test_nodata_is_not_success_and_controls_are_separate(self):
        q = dns.query("youtube.com", "A")
        self.assertEqual(dns.usability(dns.decode(response(q), q), "positive"), "no-usable-answer")
        negative = dns.decode(response(q, flags=0x8183), q)
        self.assertEqual(dns.usability(negative, "positive"), "rcode-failure")
        self.assertEqual(dns.usability(negative, "nxdomain"), "expected-nxdomain")
        self.assertEqual(dns.usability(dns.decode(response(q), q), "nxdomain"), "unexpected-control-result")

    def test_truncation_and_bogus_address_are_not_usable(self):
        q = dns.query("youtube.com", "A")
        truncated = dns.decode(response(q, flags=0x8380), q)
        self.assertEqual(dns.usability(truncated, "positive"), "truncated")
        for addr in (b"\x00" * 4, b"\x7f\0\0\1"):
            r = dns.decode(response(q, records=[rr(1, addr)]), q)
            self.assertEqual(dns.usability(r, "positive"), "no-usable-answer")

    def test_cname_chain_only(self):
        q = dns.query("youtube.com", "A")
        target = b"\x03cdn\x07example\x03com\0"
        r = dns.decode(response(q, records=[rr(5, target), rr(1, b"\x08" * 4, owner=target)]), q)
        self.assertEqual(dns.usability(r, "positive"), "usable-answer")
        r = dns.decode(response(q, records=[rr(1, b"\x08" * 4, owner=target)]), q)
        self.assertEqual(dns.usability(r, "positive"), "no-usable-answer")

    def test_soa_and_original_rdata_preserved(self):
        q = dns.query("vpn-dns-control.invalid", "A")
        soa = b"\0\0" + struct.pack("!5I", 1, 2, 3, 4, 5)
        r = dns.decode(response(q, flags=0x8183, authority=[rr(6, soa)]), q)
        self.assertEqual(r["authority"][0]["soa"]["values"], [1, 2, 3, 4, 5])
        self.assertEqual(r["authority"][0]["rdata_hex"], soa.hex())

    def test_malformed_or_mismatched_responses(self):
        q = dns.query("youtube.com", "A")
        good = response(q)
        bads = [b"", good[:8], good + b"x", bytes([good[0] ^ 1]) + good[1:],
                response(q, flags=0x0100), good[:12] + b"\xc0\x0c" + good[-4:],
                response(q, records=[rr(1, b"\x08")]),
                response(q, records=[rr(1, b"\x08" * 4)])[:-1]]
        for bad in bads:
            with self.subTest(bad=bad), self.assertRaises((ValueError, struct.error)):
                dns.decode(bad, q)

    @patch.object(dns.socket, "socket")
    def test_udp_never_falls_back(self, create):
        sock = create.return_value.__enter__.return_value
        sock.recv.return_value = b"truncated"
        self.assertEqual(dns.exchange("udp", PLAN["resolver"], b"query", {}), b"truncated")
        create.assert_called_once_with(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect.assert_called_once_with(("1.1.1.1", 53))
        sock.send.assert_called_once_with(b"query")

    @patch.object(dns.ssl, "create_default_context")
    @patch.object(dns.socket, "socket")
    def test_dot_has_hostname_verification_and_independent_bootstrap(self, create, default_context):
        raw = create.return_value.__enter__.return_value
        tls = default_context.return_value.wrap_socket.return_value
        tls.recv.side_effect = [b"\0\x04", b"an", b"sw"]
        result = {}
        self.assertEqual(dns.exchange("dot", PLAN["resolver"], b"q", result), b"answ")
        raw.connect.assert_called_once_with(("1.1.1.1", 853))
        default_context.assert_called_once_with()
        default_context.return_value.wrap_socket.assert_called_once_with(raw, server_hostname="cloudflare-dns.com")
        tls.sendall.assert_called_once_with(b"\0\x01q")
        self.assertTrue(result["tls_verified"])

    @patch.object(dns.http.client, "HTTPResponse")
    @patch.object(dns.ssl, "create_default_context")
    @patch.object(dns.socket, "socket")
    def test_doh_checks_status_type_encoding_and_size(self, create, default_context, http):
        response_mock = http.return_value.__enter__.return_value
        tls = default_context.return_value.wrap_socket.return_value
        cases = [(302, "application/dns-message", "identity", b"", "http-status"),
                 (200, "text/html", "identity", b"", "http-content-type"),
                 (200, "application/dns-message", "gzip", b"", "http-content-encoding"),
                 (200, "application/dns-message", "identity", b"x" * 65536, "response-too-large")]
        for status, content_type, encoding, payload, error in cases:
            response_mock.status = status
            response_mock.getheader.side_effect = lambda name, default=None: {
                "Content-Type": content_type, "Content-Encoding": encoding}.get(name, default)
            response_mock.read.return_value = payload
            with self.subTest(error=error), self.assertRaisesRegex(dns.DiagnosticError, error):
                dns.exchange("doh", PLAN["resolver"], b"q", {})
        create.return_value.__enter__.return_value.connect.assert_called_with(("1.1.1.1", 443))
        self.assertIn(b"Host: cloudflare-dns.com\r\n", tls.sendall.call_args.args[0])
        self.assertEqual(create.call_count, len(cases))  # No redirect, retry or fallback.

    @patch.object(dns.signal, "setitimer")
    @patch.object(dns, "exchange")
    def test_distinct_failures_and_redacted_errors(self, exchange, timer):
        for error, outcome in ((TimeoutError("secret"), "timeout"),
                               (ssl.SSLCertVerificationError("secret"), "tls-verification-failure"),
                               (ssl.SSLError("secret"), "tls-failure"),
                               (OSError("secret"), "transport-error"),
                               (dns.DiagnosticError("http-status"), "http-status")):
            exchange.side_effect = error
            r = dns.explicit_check("dot", PLAN["resolver"], PLAN["names"][0], "A", False)
            self.assertEqual(r["outcome"], outcome)
            self.assertNotIn("secret", json.dumps(r))
            self.assertEqual(timer.call_args.args, (dns.signal.ITIMER_REAL, 0))
        exchange.side_effect = None
        exchange.return_value = b"bad-dns"
        r = dns.explicit_check("doh", PLAN["resolver"], PLAN["names"][0], "A", False)
        self.assertEqual(r["outcome"], "malformed-dns")
        self.assertEqual(dns.base64.b64decode(r["response_b64"]), b"bad-dns")

    @patch.object(dns.subprocess, "run")
    def test_libc_is_separate_bounded_process(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, b'{"outcome":"gaierror","gai_errno":-3}')
        result = dns.libc_check("youtube.com", "A")
        self.assertEqual(result["gai_errno"], -3)
        self.assertEqual(result["mode"], "libc-nss")
        self.assertEqual(run.call_args.kwargs["timeout"], 4)
        run.side_effect = subprocess.TimeoutExpired("private", 4)
        self.assertEqual(dns.libc_check("youtube.com", "A")["outcome"], "timeout")

    @patch.object(dns.time, "sleep")
    @patch.object(dns, "libc_check", return_value={"outcome": "timeout"})
    @patch.object(dns, "explicit_check", return_value={"outcome": "timeout"})
    def test_all_failures_still_complete_with_finite_count(self, check, libc, sleep):
        rows = []
        dns.run(PLAN, rows.append)
        self.assertEqual(check.call_count, 26)
        self.assertEqual(libc.call_count, 8)
        self.assertEqual(rows[-1]["diagnostic_completion"], "complete")
        self.assertEqual(rows[-1]["route_status"], "route-unverified")
        for i in range(0, 24, 4):
            udp, tcp = check.call_args_list[i:i + 2]
            self.assertEqual(udp.args[1:], tcp.args[1:])
        self.assertIn(unittest.mock.call(5), sleep.call_args_list)

    @patch.object(dns.os, "getuid", return_value=1000)
    @patch.object(dns.sys, "argv", ["dns_diag.py", "--gate", "/unused"])
    @patch("builtins.print")
    def test_intercepted_uid_cannot_probe(self, output, uid):
        with patch.object(dns, "run") as run:
            self.assertEqual(dns.main(), 1)
            run.assert_not_called()

    def test_eof_and_timeout_handlers(self):
        sock = MagicMock()
        sock.recv.return_value = b""
        with self.assertRaises(dns.DiagnosticError):
            dns.recv_exact(sock, 2)
        with self.assertRaises(TimeoutError):
            dns.alarm_timeout(None, None)
        with self.assertRaises(KeyboardInterrupt):
            dns.cancel(None, None)


if __name__ == "__main__":
    unittest.main()
