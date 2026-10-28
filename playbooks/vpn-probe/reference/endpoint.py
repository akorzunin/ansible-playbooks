#!/usr/bin/env python3
"""Finite, single-lease HTTPS objects and authenticated UDP echo. No proxying.

No request logging. All source addresses and receipts are private lease state.
Restart deliberately fails closed: a new lease requires teardown and new keys.
"""
import argparse
import hashlib
import hmac
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import secrets
import socket
import socketserver
import ssl
import struct
import threading
import time

BLOCK = 65536
OBJECTS = {"fresh": 4096, "segment": 8388608, "continuous": 4294967296}
RATE = 8388608  # 2x the proposed client's aggregate 4 MiB/s; not a capacity claim.
BYTE_BUDGET = 4294967296
MAX_REQUESTS = 1024
PACKET = struct.Struct("!4s16sId32s32s")  # 96 bytes, including the HMAC.
ID = re.compile(r"[a-zA-Z0-9_-]{1,64}\Z")


def blocks(size):
    """Counter-separated SHAKE256, 64 KiB blocks (<=128 KiB transient payload)."""
    for index in range((size + BLOCK - 1) // BLOCK):
        yield hashlib.shake_256(b"vpn-reference-v1\0" + index.to_bytes(8, "big")).digest(
            min(BLOCK, size - index * BLOCK)
        )


def object_manifest():
    result = {}
    for name, size in OBJECTS.items():
        digest = hashlib.sha256()
        for block in blocks(size):
            digest.update(block)
        result[name] = {"object_bytes": size, "sha256": digest.hexdigest()}
    return result


def validate(config, now=None):
    expected = {"schema_version", "bind_ipv4", "sources", "run", "expires",
                "token", "receipt_token", "objects"}
    if set(config) != expected or config["schema_version"] != 1:
        raise ValueError("config-schema")
    address = ipaddress.IPv4Address(config["bind_ipv4"])
    if address.is_unspecified or address.is_multicast:
        raise ValueError("bind-address")
    if not isinstance(config["sources"], list) or not 1 <= len(config["sources"]) <= 8:
        raise ValueError("sources")
    for source in config["sources"]:
        network = ipaddress.IPv4Network(source, strict=True)
        if network.prefixlen != 32 or network.network_address.is_unspecified or network.is_multicast:
            raise ValueError("source-must-be-host")
    if not ID.fullmatch(config["run"]):
        raise ValueError("run")
    for key in ("token", "receipt_token"):
        if not re.fullmatch(r"[0-9a-f]{64}", config[key]):
            raise ValueError("token")
    if config["token"] == config["receipt_token"]:
        raise ValueError("separate-receipt-token")
    now = time.time() if now is None else now
    if not isinstance(config["expires"], int) or not now < config["expires"] <= now + 900:
        raise ValueError("lease-expired-or-too-long")
    if set(config["objects"]) != set(OBJECTS):
        raise ValueError("objects")
    for name, size in OBJECTS.items():
        obj = config["objects"][name]
        if set(obj) != {"object_bytes", "sha256"} or obj["object_bytes"] != size or not re.fullmatch(r"[0-9a-f]{64}", obj["sha256"]):
            raise ValueError("object-manifest")
    return config


def private_json(path):
    path = Path(path)
    if (path.is_symlink() or path.stat().st_uid != os.geteuid()
            or path.stat().st_mode & 0o077 or path.stat().st_size > 16384):
        raise ValueError("insecure-input")
    return json.loads(path.read_text())


def credential_json(path):
    """Read only the selected config from systemd's read-only credential mount.

    DynamicUser credentials can be root:root 0440 with a worker-only read ACL,
    or use the worker's private GID. Controller files still need private_json.
    """
    root = Path(os.environ["CREDENTIALS_DIRECTORY"])
    path = Path(path)
    if (not root.is_absolute() or root.resolve() != root or path != root / "config.json"
            or path.is_symlink() or not os.statvfs(root).f_flag & os.ST_RDONLY):
        raise ValueError("insecure-credential-path")
    info = path.stat()
    if (info.st_uid not in (0, os.geteuid()) or info.st_gid not in (0, os.getegid())
            or info.st_mode & 0o777 not in (0o400, 0o440) or info.st_size > 16384):
        raise ValueError("insecure-credential")
    return json.loads(path.read_text())


class Rejected(Exception):
    def __init__(self, status):
        self.status = status


class Lease:
    def __init__(self, config, clock=time.monotonic, wall=time.time):
        self.config = config
        self.clock, self.wall = clock, wall
        self.end = clock() + max(0, config["expires"] - wall())
        self.lock = threading.Lock()
        self.used = set()
        self.receipts = {}
        self.sessions = {}
        self.active = 0
        self.budget = BYTE_BUDGET
        self.next_send = clock()

    def allowed(self, source):
        return source + "/32" in self.config["sources"]

    def alive(self):
        return self.clock() < self.end and self.wall() < self.config["expires"]

    def authorize(self, headers, source, receipt=False):
        # Single global lock: <=8 HTTP workers and 4 UDP sessions; shard if expanded.
        with self.lock:
            if not self.allowed(source) or not self.alive():
                raise Rejected(403)
            token = self.config["receipt_token" if receipt else "token"]
            if not hmac.compare_digest(headers.get("authorization", ""), "Bearer " + token):
                raise Rejected(401)
            request = headers.get("x-request-id", "")
            if headers.get("x-run-id") != self.config["run"] or not ID.fullmatch(request):
                raise Rejected(400)
            if request in self.used:
                raise Rejected(409)
            if len(self.used) >= MAX_REQUESTS:
                raise Rejected(429)
            self.used.add(request)
            return request

    def reserve(self, size):
        with self.lock:
            if not self.alive() or self.budget < size:
                raise Rejected(429)
            self.budget -= size  # Failed sends remain charged; never exceed budget.
            now = self.clock()
            ready = max(now, self.next_send)
            self.next_send = ready + size / RATE
            return max(0, ready - now)

    def new_session(self, source):
        with self.lock:
            # No recycling: a lease has at most four sessions, even after expiry.
            if len(self.sessions) >= 4:
                raise Rejected(429)
            sid = secrets.token_bytes(16)
            session = {"key": secrets.token_bytes(32), "source": source, "peer": None,
                       "end": min(self.end, self.clock() + 600), "seen": bytearray(3750),
                       "received": 0, "sent": 0, "duplicates": 0, "reordered": 0,
                       "rate_drops": 0, "highest": -1, "rate_at": self.clock(), "tokens": 10.0,
                       "first": None, "last": None}
            self.sessions[sid] = session
            return {"session": sid.hex(), "key": session["key"].hex(),
                    "duration_s": max(0, session["end"] - self.clock()),
                    "packet_bytes": PACKET.size, "max_packets": 30000,
                    "pps": 100, "burst": 10, "measurement_pps": 50}

    def udp(self, data, peer, send):
        if len(data) != PACKET.size or not self.allowed(peer[0]):
            return
        magic, sid, seq, stamp, payload, mac = PACKET.unpack(data)
        with self.lock:
            session = self.sessions.get(sid)
            now = self.clock()
            if (not self.alive() or session is None or now >= session["end"]
                    or peer[0] != session["source"] or magic != b"VRU1"
                    or seq >= 30000 or not math.isfinite(stamp)
                    or not hmac.compare_digest(mac, hmac.digest(session["key"], data[:-32], "sha256"))):
                return
            if session["peer"] is not None and peer != session["peer"]:
                return
            byte, bit = divmod(seq, 8)
            if session["seen"][byte] & (1 << bit):
                session["duplicates"] += 1
                return
            # 2x intended 50 pps plus a small burst: don't count normal jitter as loss.
            session["tokens"] = min(10.0, session["tokens"] + (now - session["rate_at"]) * 100)
            session["rate_at"] = now
            if session["tokens"] < 1:
                session["rate_drops"] += 1
                return
            session["tokens"] -= 1
            session["peer"] = peer
            session["seen"][byte] |= 1 << bit
            session["received"] += 1
            session["reordered"] += int(seq < session["highest"])
            session["highest"] = max(seq, session["highest"])
            session["first"] = now if session["first"] is None else session["first"]
            session["last"] = now
            reply = PACKET.pack(b"VRR1", sid, seq, stamp, payload, b"\0" * 32)
            reply = reply[:-32] + hmac.digest(session["key"], reply[:-32], "sha256")
            try:
                send(reply, peer)
                session["sent"] += 1
            except OSError:
                pass

    def udp_receipt(self, sid):
        with self.lock:
            session = self.sessions.get(bytes.fromhex(sid)) if re.fullmatch(r"[0-9a-f]{32}", sid) else None
            if session is None:
                raise Rejected(404)
            return {key: session[key] for key in ("source", "received", "sent", "duplicates",
                                                 "reordered", "rate_drops", "highest", "first", "last")} | {
                "seen_bitmap_hex": session["seen"].hex(), "run": self.config["run"]}


def read_request(stream):
    """Strict tiny HTTP/1.1 subset: <=8 KiB headers, no bodies or pipelining."""
    line = stream.readline(4097)
    if len(line) > 4096:
        raise Rejected(400)
    parts = line.decode("ascii").rstrip("\r\n").split(" ")
    if len(parts) != 3 or parts[2] != "HTTP/1.1":
        raise Rejected(400)
    method, path, _ = parts
    headers, total = {}, len(line)
    for _ in range(32):
        line = stream.readline(4097)
        total += len(line)
        if total > 8192 or not line.endswith(b"\r\n"):
            raise Rejected(400)
        if line == b"\r\n":
            break
        key, separator, value = line.decode("ascii").partition(":")
        key = key.lower()
        if not separator or not re.fullmatch(r"[a-z0-9-]+", key) or key in headers:
            raise Rejected(400)
        headers[key] = value.strip()
    else:
        raise Rejected(400)
    if (method not in {"GET", "POST"} or "host" not in headers or "transfer-encoding" in headers
            or headers.get("content-length", "0") != "0" or "range" in headers):
        raise Rejected(400)
    return method, path, headers


def response(sock, status, size, content_type):
    sock.sendall((f"HTTP/1.1 {status} Response\r\nContent-Length: {size}\r\n"
                  f"Content-Type: {content_type}\r\nCache-Control: no-store, no-transform\r\n"
                  "Connection: close\r\nX-Content-Type-Options: nosniff\r\n\r\n").encode())


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        lease = self.server.lease
        if not lease.allowed(self.client_address[0]) or not lease.alive():
            return
        try:
            self.request.settimeout(3)
            with self.server.tls.wrap_socket(self.request, server_side=True) as sock:
                # Absolute header deadline, not a per-read slowloris timeout.
                timer = threading.Timer(5, self.close_socket, args=(sock,))
                timer.daemon = True
                timer.start()
                try:
                    self.serve(sock, timer)
                finally:
                    timer.cancel()
        except (OSError, ValueError, UnicodeError):
            pass  # Never log headers, paths, TLS errors or source mappings.

    @staticmethod
    def close_socket(sock):
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def serve(self, sock, header_timer=None):
        lease = self.server.lease
        started = lease.clock()
        try:
            with sock.makefile("rb") as stream:
                method, path, headers = read_request(stream)
            if header_timer is not None:
                header_timer.cancel()
            receipt = path.startswith("/receipts/") or path.startswith("/udp/")
            request = lease.authorize(headers, self.client_address[0], receipt)
            if method == "GET" and path.startswith("/objects/"):
                name = path.removeprefix("/objects/")
                if name not in OBJECTS:
                    raise Rejected(404)
                self.object(sock, name, request, started)
                return
            if method == "POST" and path == "/udp-session":
                result = lease.new_session(self.client_address[0])
            elif method == "GET" and path.startswith("/receipts/"):
                with lease.lock:
                    result = lease.receipts.get(path.removeprefix("/receipts/"))
                if result is None:
                    raise Rejected(404)
            elif method == "GET" and path.startswith("/udp/"):
                result = lease.udp_receipt(path.removeprefix("/udp/"))
            else:
                raise Rejected(404)
            data = json.dumps(result, separators=(",", ":")).encode()
            response(sock, 200, len(data), "application/json")
            sock.sendall(data)
        except Rejected as exc:
            response(sock, exc.status, 0, "application/octet-stream")

    def object(self, sock, name, request, started):
        lease = self.server.lease
        with lease.lock:
            if lease.active >= 4:
                raise Rejected(429)
            lease.active += 1
        sent, outcome = 0, "interrupted"
        receipt = {"run": lease.config["run"], "request": request, "source": self.client_address[0],
                   "object": name, "utc_start": lease.wall(), "body_bytes_sent": 0,
                   "elapsed_s": 0, "outcome": "active"}
        with lease.lock:
            lease.receipts[request] = receipt
        try:
            response(sock, 200, OBJECTS[name], "application/octet-stream")
            for block in blocks(OBJECTS[name]):
                if lease.clock() - started >= 660:
                    outcome = "deadline"
                    break
                try:
                    delay = lease.reserve(len(block))
                except Rejected:
                    outcome = "budget-or-expiry"
                    break
                time.sleep(delay)
                if not lease.alive():
                    outcome = "expired"
                    break
                sock.settimeout(min(2, max(0.001, lease.end - lease.clock())))
                sock.sendall(block)
                sent += len(block)
            else:
                outcome = "complete"
        finally:
            with lease.lock:
                lease.active -= 1
                lease.receipts[request] = receipt | {"body_bytes_sent": sent,
                    "elapsed_s": lease.clock() - started, "outcome": outcome}


class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 8

    def __init__(self, address, tls, lease):
        self.tls, self.lease = tls, lease
        self.slots = threading.BoundedSemaphore(8)
        self.connections = self.window_count = 0
        self.window = lease.clock()
        super().__init__(address, Handler)

    def admit(self, source):
        # Called only by the single accept loop, including unauthenticated clients.
        if not self.lease.allowed(source) or not self.lease.alive():
            return False
        now = self.lease.clock()
        if now - self.window >= 1:
            self.window, self.window_count = now, 0
        if self.connections >= 2048 or self.window_count >= 32:
            return False
        self.connections += 1
        self.window_count += 1
        return True

    def process_request(self, request, client_address):
        if not self.admit(client_address[0]) or not self.slots.acquire(False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        pass  # socketserver's default traceback includes private addresses.


def run(config, cert, key, state):
    validate(config)
    if os.geteuid() == 0:
        raise ValueError("unprivileged-worker-required")
    # A persistent marker prevents replay/budget reset after process crashes.
    fd = os.open(Path(state) / "spent", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.fsync(fd)
    os.close(fd)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(cert, key)
    lease = Lease(config)
    with Server((config["bind_ipv4"], 9443), tls, lease) as server, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        udp.bind((config["bind_ipv4"], 9444))
        udp.settimeout(0.25)
        server.timeout = 0.25

        def receive():
            while lease.alive():
                try:
                    data, peer = udp.recvfrom(PACKET.size + 1)
                    lease.udp(data, peer, udp.sendto)
                except socket.timeout:
                    continue
                except OSError:
                    return

        threading.Thread(target=receive, daemon=True).start()
        while lease.alive():
            server.handle_request()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        config = validate(private_json(args.config) if args.check else credential_json(args.config))
        if not args.check:
            credential = Path(os.environ["CREDENTIALS_DIRECTORY"])
            run(config, credential / "cert.pem", credential / "key.pem", os.environ["STATE_DIRECTORY"])
    except (OSError, ValueError, KeyError, TypeError):
        parser.exit(1, "reference endpoint: input/startup failure (details suppressed)\n")


if __name__ == "__main__":
    main()
