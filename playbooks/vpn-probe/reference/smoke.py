#!/usr/bin/env python3
"""Opt-in, finite same-host readiness ONLY: six HTTPS operations, one UDP packet.

No execution is authorized by this source. No throughput or route qualification.
Run unprivileged with only config.json and ca.pem as systemd credentials.
"""
from contextlib import closing
import hashlib
import hmac
import http.client
import json
import os
from pathlib import Path
import socket
import ssl
import struct
import time


def main(evidence):
    if os.geteuid() == 0:
        raise ValueError("unprivileged-only")
    root = Path(os.environ["CREDENTIALS_DIRECTORY"])
    config = json.loads((root / "config.json").read_text())
    tls = ssl.create_default_context(cafile=root / "ca.pem")
    host = config["bind_ipv4"]
    prefix = os.urandom(8).hex()

    def request(method, path, number, receipt=False, unauthorized=False):
        token = config["receipt_token" if receipt else "token"]
        headers = {"Authorization": "Bearer " + ("0" * 64 if unauthorized else token),
                   "X-Run-ID": config["run"], "X-Request-ID": f"smoke-{prefix}-{number}"}
        evidence["https_operations"] += 1
        with closing(http.client.HTTPSConnection(host, 9443, context=tls, timeout=4)) as connection:
            connection.request(method, path, headers=headers)
            reply = connection.getresponse()
            body = reply.read(16385)
            evidence["http"].append({"stage": evidence["stage"], "status": reply.status, "bytes": len(body)})
            if len(body) > 16384 or reply.getheader("Content-Encoding") is not None:
                raise ValueError("unexpected-response")
            return reply.status, body

    evidence["stage"] = "bad-bearer"
    assert request("GET", "/objects/fresh", 0, unauthorized=True)[0] == 401
    evidence["stage"] = "fresh-object"
    status, body = request("GET", "/objects/fresh", 1)
    assert status == 200 and len(body) == 4096
    assert hashlib.sha256(body).hexdigest() == config["objects"]["fresh"]["sha256"]
    evidence["stage"] = "replayed-id"
    assert request("GET", "/objects/fresh", 1)[0] == 409
    evidence["stage"] = "object-receipt"
    status, body = request("GET", f"/receipts/smoke-{prefix}-1", 2, receipt=True)
    receipt = json.loads(body)
    evidence["object_receipt"] = {"bytes": receipt.get("body_bytes_sent"),
                                  "complete": receipt.get("outcome") == "complete",
                                  "source_matches_bind": receipt.get("source") == host}
    assert status == 200 and receipt["body_bytes_sent"] == 4096 and receipt["outcome"] == "complete"
    evidence["stage"] = "udp-registration"
    status, body = request("POST", "/udp-session", 3)
    assert status == 200
    session = json.loads(body)
    wire = struct.Struct("!4s16sId32s32s")
    packet = wire.pack(b"VRU1", bytes.fromhex(session["session"]), 0, time.monotonic(), os.urandom(32), b"\0" * 32)
    key = bytes.fromhex(session["key"])
    packet = packet[:-32] + hmac.digest(key, packet[:-32], "sha256")
    evidence["stage"] = "udp-echo"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        udp.settimeout(4)
        udp.connect((host, 9444))
        udp.send(packet)
        evidence["udp_packets"] += 1
        reply = udp.recv(97)
        evidence["udp_reply_bytes"] = len(reply)
    assert len(reply) == 96 and reply[:4] == b"VRR1" and reply[4:-32] == packet[4:-32]
    assert hmac.compare_digest(reply[-32:], hmac.digest(key, reply[:-32], "sha256"))
    evidence["stage"] = "udp-receipt"
    status, body = request("GET", f"/udp/{session['session']}", 4, receipt=True)
    stats = json.loads(body)
    evidence["udp_receipt"] = {"received": stats.get("received"), "sent": stats.get("sent"),
                               "source_matches_bind": stats.get("source") == host}
    assert status == 200 and stats["received"] == stats["sent"] == 1
    evidence.update({"readiness": "passed", "stage": "complete",
                     "scope": "same-host-only; no route or capacity qualification"})


if __name__ == "__main__":
    evidence = {"readiness": "failed", "stage": "input", "https_operations": 0, "udp_packets": 0, "http": []}
    try:
        main(evidence)
    except Exception as exc:
        evidence["error_type"] = type(exc).__name__  # Never include raw errors, bodies or keys.
        print(json.dumps(evidence))
        raise SystemExit(1) from None
    print(json.dumps(evidence))
