#!/usr/bin/env python3
"""Bounded Linux DNS diagnosis. Private JSONL on stdout; no route qualification implied."""
import argparse
import base64
import datetime
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import ssl
import struct
import subprocess
import sys
import time

TIMEOUT = 4
MAX_WIRE = 65535
TYPES = {"A": 1, "AAAA": 28}


class DiagnosticError(Exception):
    pass


def validate_plan(plan):
    if set(plan) != {"resolver", "names", "edns"} or type(plan["edns"]) is not bool:
        raise ValueError("Invalid plan")
    resolver = plan["resolver"]
    if set(resolver) != {"alias", "ipv4", "tls_name", "doh_path"}:
        raise ValueError("Invalid resolver")
    ipaddress.IPv4Address(resolver["ipv4"])
    if not re.fullmatch(r"[a-z0-9_-]{1,40}", resolver["alias"]):
        raise ValueError("Invalid alias")
    hostname(resolver["tls_name"])
    if resolver["doh_path"] != "/dns-query":
        raise ValueError("Only /dns-query supported")
    names = plan["names"]
    if len(names) != 3 or len({n["alias"] for n in names}) != 3:
        raise ValueError("Require three distinct controls")
    for item in names:
        if set(item) != {"alias", "name", "expect"}:
            raise ValueError("Invalid control")
        hostname(item["name"])
        if not re.fullmatch(r"[a-z0-9_-]{1,40}", item["alias"]):
            raise ValueError("Invalid alias")
    if [n["expect"] for n in names] != ["positive", "positive", "nxdomain"]:
        raise ValueError("Require two positive controls then NXDOMAIN control")
    return plan


def hostname(value):
    if not isinstance(value, str) or len(value) > 253 or not all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in value.split(".")
    ):
        raise ValueError("Invalid DNS name")
    return value


def query(name, qtype, edns=False):
    wire_name = b"".join(bytes([len(label)]) + label.encode("ascii") for label in hostname(name).split(".")) + b"\0"
    header = struct.pack("!6H", secrets.randbelow(65536), 0x0100, 1, 0, 0, int(edns))
    opt = b"\0" + struct.pack("!HHIH", 41, 1232, 0, 0) if edns else b""
    return header + wire_name + struct.pack("!HH", TYPES[qtype], 1) + opt


def dns_name(data, offset):
    labels, seen, end = [], set(), None
    while True:
        if offset >= len(data) or offset in seen:
            raise ValueError("Invalid DNS name")
        seen.add(offset)
        size = data[offset]
        if size & 0xC0 == 0xC0:
            if offset + 1 >= len(data):
                raise ValueError("Short pointer")
            if end is None:
                end = offset + 2
            offset = ((size & 63) << 8) | data[offset + 1]
            continue
        if size & 0xC0 or offset + 1 + size > len(data):
            raise ValueError("Invalid label")
        offset += 1
        if not size:
            return ".".join(labels).lower(), end or offset
        labels.append(data[offset:offset + size].decode("ascii"))
        if sum(len(label) + 1 for label in labels) > 254:
            raise ValueError("Oversized name")
        offset += size


def decode(data, request):
    if len(data) < 12 or len(data) > MAX_WIRE:
        raise ValueError("Invalid DNS length")
    ident, flags, qd, an, ns, ar = struct.unpack_from("!6H", data)
    expected_name, qend = dns_name(request, 12)
    expected_question = struct.unpack_from("!HH", request, qend)
    if ident != struct.unpack_from("!H", request)[0] or not flags & 0x8000 or flags & 0x7800 or qd != 1:
        raise ValueError("Mismatched response")
    name, offset = dns_name(data, 12)
    question = struct.unpack_from("!HH", data, offset)
    if name != expected_name or question != expected_question:
        raise ValueError("Mismatched question")
    offset += 4
    result = {"flags": flags, "tc": bool(flags & 0x0200), "ad": bool(flags & 0x0020),
              "rcode": flags & 15, "question": {"name": name, "type": question[0], "class": question[1]}}
    for section, count in (("answer", an), ("authority", ns), ("additional", ar)):
        records = []
        for _ in range(count):
            owner, offset = dns_name(data, offset)
            kind, cls, ttl, size = struct.unpack_from("!HHIH", data, offset)
            offset += 10
            end = offset + size
            if end > len(data):
                raise ValueError("Short RDATA")
            raw = data[offset:end]
            record = {"name": owner, "type": kind, "class": cls, "ttl": ttl, "rdata_hex": raw.hex()}
            if kind in (1, 28):
                if size != (4 if kind == 1 else 16):
                    raise ValueError("Invalid address")
                record["address"] = str(ipaddress.ip_address(raw))
            elif kind in (2, 5, 12):
                record["target"], consumed = dns_name(data, offset)
                if consumed != end:
                    raise ValueError("Invalid name RDATA")
            elif kind == 6:
                mname, pos = dns_name(data, offset)
                rname, pos = dns_name(data, pos)
                if pos + 20 != end:
                    raise ValueError("Invalid SOA")
                record["soa"] = {"mname": mname, "rname": rname,
                                 "values": list(struct.unpack_from("!5I", data, pos))}
            elif kind == 41:
                result["rcode"] |= (ttl >> 24) << 4
            records.append(record)
            offset = end
        result[section] = records
    if offset != len(data):
        raise ValueError("Trailing DNS bytes")
    return result


def usability(response, expectation):
    if response["tc"]:
        return "truncated"
    if expectation == "nxdomain":
        return "expected-nxdomain" if response["rcode"] == 3 and not response["answer"] else "unexpected-control-result"
    if response["rcode"] != 0:
        return "rcode-failure"
    reachable = {response["question"]["name"]}
    # Bounded response-chain scan; this is DNS diagnosis, not a validating resolver.
    for _ in range(len(response["answer"])):
        reachable.update(r["target"] for r in response["answer"]
                         if r["type"] == 5 and r["class"] == 1 and r["name"] in reachable)
    addresses = [r["address"] for r in response["answer"]
                 if r["type"] == response["question"]["type"] and r["class"] == 1
                 and r["name"] in reachable and "address" in r]
    return "usable-answer" if any(ipaddress.ip_address(a).is_global for a in addresses) else "no-usable-answer"


def recv_exact(sock, count):
    chunks = bytearray()
    while len(chunks) < count:
        block = sock.recv(count - len(chunks))
        if not block:
            raise DiagnosticError("unexpected-eof")
        chunks.extend(block)
    return bytes(chunks)


def exchange(mode, resolver, wire, evidence):
    port = {"udp": 53, "tcp": 53, "dot": 853, "doh": 443}[mode]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM if mode == "udp" else socket.SOCK_STREAM) as raw:
        raw.settimeout(TIMEOUT)
        evidence["stage"] = "udp" if mode == "udp" else "tcp"
        raw.connect((resolver["ipv4"], port))
        evidence.update(local=raw.getsockname(), peer=raw.getpeername(), outer_family="ipv4")
        if mode == "udp":
            raw.send(wire)
            return raw.recv(MAX_WIRE)  # No TCP fallback, including when TC is set.
        sock = raw
        try:
            if mode in ("dot", "doh"):
                evidence["stage"] = "tls"
                context = ssl.create_default_context()
                sock = context.wrap_socket(raw, server_hostname=resolver["tls_name"])
                evidence.update(tls_verified=True, tls_version=sock.version())
            if mode == "doh":
                evidence["stage"] = "http"
                # Fixed bootstrap IP above; retain hostname for both SNI and Host.
                headers = (f"POST {resolver['doh_path']} HTTP/1.1\r\nHost: {resolver['tls_name']}\r\n"
                           f"Content-Type: application/dns-message\r\nAccept: application/dns-message\r\n"
                           f"Accept-Encoding: identity\r\nContent-Length: {len(wire)}\r\nConnection: close\r\n\r\n")
                sock.sendall(headers.encode("ascii") + wire)
                with http.client.HTTPResponse(sock) as response:
                    response.begin()
                    evidence["http_status"] = response.status
                    if response.status != 200:
                        raise DiagnosticError("http-status")
                    if response.getheader("Content-Type", "").split(";")[0].strip().lower() != "application/dns-message":
                        raise DiagnosticError("http-content-type")
                    if response.getheader("Content-Encoding", "identity").lower() != "identity":
                        raise DiagnosticError("http-content-encoding")
                    payload = response.read(MAX_WIRE + 1)
                    if len(payload) > MAX_WIRE:
                        raise DiagnosticError("response-too-large")
                    return payload
            evidence["stage"] = "dns-framing"
            sock.sendall(struct.pack("!H", len(wire)) + wire)
            return recv_exact(sock, struct.unpack("!H", recv_exact(sock, 2))[0])
        finally:
            if sock is not raw:
                sock.close()


def alarm_timeout(_signum, _frame):
    raise TimeoutError()


def cancel(_signum, _frame):
    raise KeyboardInterrupt()


def explicit_check(mode, resolver, name, qtype, edns):
    started = time.monotonic()
    wire = query(name["name"], qtype, edns)
    result = {"mode": mode, "resolver": resolver["alias"], "name": name["alias"], "qtype": qtype,
              "expect": name["expect"], "edns": edns, "rd": True, "do": False,
              "query_b64": base64.b64encode(wire).decode(), "stage": "input"}
    signal.setitimer(signal.ITIMER_REAL, TIMEOUT)
    try:
        response = exchange(mode, resolver, wire, result)
        result["response_b64"] = base64.b64encode(response).decode()
        result["stage"] = "dns-decode"
        result["dns"] = decode(response, wire)
        result["usability"] = usability(result["dns"], name["expect"])
        result["outcome"] = "response"
    except TimeoutError:
        result.update(outcome="timeout", usability="unusable")
    except ssl.SSLCertVerificationError:
        result.update(outcome="tls-verification-failure", usability="unusable")
    except ssl.SSLError:
        result.update(outcome="tls-failure", usability="unusable")
    except DiagnosticError as exc:
        result.update(outcome=str(exc), usability="unusable")
    except (ValueError, struct.error, UnicodeError):
        result.update(outcome="malformed-dns", usability="unusable")
    except http.client.HTTPException:
        result.update(outcome="malformed-http", usability="unusable")
    except OSError:
        result.update(outcome="transport-error", usability="unusable")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    result["elapsed_s"] = time.monotonic() - started
    return result


def libc_check(name, qtype):
    started = time.monotonic()
    try:
        child = subprocess.run([sys.executable, "-I", str(Path(__file__).resolve()), "--libc", name, qtype],
                               capture_output=True, timeout=TIMEOUT, check=False)
        result = json.loads(child.stdout) if child.returncode == 0 else {"outcome": "process-error"}
    except subprocess.TimeoutExpired:
        result = {"outcome": "timeout"}
    except (OSError, ValueError):
        result = {"outcome": "process-error"}
    return {**result, "mode": "libc-nss", "qtype": qtype, "elapsed_s": time.monotonic() - started}


def context():
    return {"uid": os.getuid(), "gid": os.getgid(), "groups": os.getgroups(), "pid": os.getpid(),
            "netns": os.readlink("/proc/self/ns/net"), "python": sys.version,
            "openssl": ssl.OPENSSL_VERSION,
            "proxy_environment_names": sorted(k for k in os.environ if "proxy" in k.lower()),
            "status": [line for line in Path("/proc/self/status").read_text().splitlines()
                       if line.startswith(("Cap", "NoNewPrivs:", "Seccomp:"))]}


def run(plan, emit):
    attempted = 0
    for name in plan["names"]:
        for qtype in TYPES:
            emit({"event": "sample", "name": name["alias"], **libc_check(name["name"], qtype)})
            for mode in ("udp", "tcp", "doh", "dot"):
                emit({"event": "sample", **explicit_check(mode, plan["resolver"], name, qtype, plan["edns"])})
                attempted += 1
                time.sleep(0.25)
    for qtype in TYPES:
        emit({"event": "sample", "name": "encrypted-resolver-bootstrap",
              **libc_check(plan["resolver"]["tls_name"], qtype)})
    time.sleep(5)
    for mode in ("doh", "dot"):
        emit({"event": "sample", "repeat": True,
              **explicit_check(mode, plan["resolver"], plan["names"][0], "A", plan["edns"])})
        attempted += 1
        time.sleep(0.25)
    emit({"event": "run-end", "diagnostic_completion": "complete", "explicit_attempts": attempted,
          "libc_attempts": 8, "route_status": "route-unverified",
          "vpn_dns": "not-run-pending-isolated-core", "application_dns": "not-run",
          "tunnel_bootstrap": "not-run-no-tunnel-started", "ipv6_transport": "not-run"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", type=Path, help="Root-created release file; no network before release")
    parser.add_argument("--libc", nargs=2, metavar=("NAME", "TYPE"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.libc:
        if os.getuid() in (0, 946, 1000):
            return 1
        name, qtype = args.libc
        try:
            addresses = sorted({item[4][0] for item in socket.getaddrinfo(
                hostname(name), None, socket.AF_INET if qtype == "A" else socket.AF_INET6, socket.SOCK_STREAM)})[:64]
            print(json.dumps({"outcome": "response", "addresses": addresses}))
        except socket.gaierror as exc:
            print(json.dumps({"outcome": "gaierror", "gai_errno": exc.errno}))
        return
    os.umask(0o077)
    signal.signal(signal.SIGALRM, alarm_timeout)
    signal.signal(signal.SIGTERM, cancel)
    started = time.monotonic()

    def emit(record):
        print(json.dumps({"schema_version": 1, "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                          "elapsed_s_run": time.monotonic() - started, **record}), flush=True)

    try:
        if os.getuid() in (0, 946, 1000) or args.gate is None:
            raise ValueError("Requires reviewed unprivileged worker and release gate")
        plan = validate_plan(json.loads(sys.stdin.buffer.read(16385)))
        emit({"event": "ready", "context": context(), "plan": plan, "route_status": "route-unverified",
              "bounds": {"explicit_queries": 26, "libc_calls": 8, "timeout_s": TIMEOUT,
                         "gate_timeout_s": 90, "max_response_bytes": MAX_WIRE, "pacing_s": 0.25}})
        deadline = time.monotonic() + 90
        while not args.gate.exists():
            if time.monotonic() >= deadline:
                raise TimeoutError()
            time.sleep(0.1)
        gate = args.gate.lstat()
        if gate.st_uid != 0 or not args.gate.is_file() or args.gate.is_symlink() or gate.st_mode & 0o022:
            raise ValueError("Unsafe release file")
        run(plan, emit)
    except (KeyboardInterrupt, SystemExit):
        emit({"event": "run-end", "diagnostic_completion": "cancelled"})
        raise
    except TimeoutError:
        emit({"event": "run-end", "diagnostic_completion": "incomplete", "error": "gate-timeout"})
        return 1
    except (ValueError, TypeError, KeyError, OSError):
        emit({"event": "run-end", "diagnostic_completion": "failed", "error": "input-or-context"})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
