#!/usr/bin/env python3
"""Prepare a NEW private lease directory offline. Plan JSON arrives on stdin.

Requires existing openssl CLI, only for a dedicated short-lived CA/leaf. Never
reads VPN certificates. Does not contact DNS, install software or deploy anything.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

import endpoint


def openssl(*args):
    subprocess.run(["openssl", *map(str, args)], check=True, capture_output=True, timeout=30)


def prepare(directory, plan):
    if set(plan) != {"bind_ipv4", "sources", "run"}:
        raise ValueError("plan-schema")
    config = endpoint.validate(plan | {"schema_version": 1, "expires": int(time.time()) + 900,
                               "token": secrets.token_hex(32), "receipt_token": secrets.token_hex(32),
                               "objects": {name: {"object_bytes": size, "sha256": "0" * 64}
                                           for name, size in endpoint.OBJECTS.items()}})
    root = Path(directory).absolute()
    if root.parent.is_symlink() or root.parent.stat().st_mode & 0o077:
        raise ValueError("private-parent-required")
    root.mkdir(mode=0o700)  # Never replace keys or reuse an existing lease directory.
    os.umask(0o077)
    # Hashing 4 GiB is streaming CPU work, not a 4 GiB file. No payload is stored.
    config["objects"] = endpoint.object_manifest()
    (root / "config.json").write_text(json.dumps(config) + "\n")
    openssl("req", "-x509", "-newkey", "ed25519", "-noenc", "-days", "2",
            "-subj", "/CN=VPN reference lease CA", "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign",
            "-keyout", root / "ca.key", "-out", root / "ca.pem")
    openssl("req", "-new", "-newkey", "ed25519", "-noenc", "-subj", "/CN=VPN reference lease",
            "-keyout", root / "key.pem", "-out", root / "leaf.csr")
    (root / "leaf.ext").write_text(
        f"subjectAltName=IP:{config['bind_ipv4']}\nbasicConstraints=critical,CA:FALSE\n"
        "keyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\n")
    openssl("x509", "-req", "-in", root / "leaf.csr", "-CA", root / "ca.pem",
            "-CAkey", root / "ca.key", "-set_serial", "1", "-days", "1",
            "-extfile", root / "leaf.ext", "-out", root / "cert.pem")
    openssl("verify", "-CAfile", root / "ca.pem", "-verify_ip", config["bind_ipv4"], root / "cert.pem")
    for name, obj in config["objects"].items():
        base = f"https://{config['bind_ipv4']}:9443"
        descriptor = {"schema_version": 1, "alias": "reference-on-vpn", "https_url": f"{base}/objects/{name}",
                      "auth_header": "Authorization: Bearer " + config["token"], "family": "ipv4",
                      "expected_status": 200, "content_type": "application/octet-stream", **obj,
                      "cache_policy": "no-store, no-transform", "receipt_url": f"{base}/receipts/{{request}}",
                      "receipt_auth_header": "Authorization: Bearer " + config["receipt_token"],
                      "location": "vpn-host", "ca_file": str(root / "ca.pem"), "run_id": config["run"],
                      "expires_at": config["expires"]}
        (root / f"{name}.json").write_text(json.dumps(descriptor) + "\n")
    # The CA key never goes to Cherry. Unlink, not guaranteed secure storage erasure.
    for name in ("ca.key", "leaf.csr", "leaf.ext"):
        (root / name).unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        prepare(args.output, json.load(sys.stdin))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        parser.exit(1, "reference preparation failed; inspect/remove only the new private directory\n")


if __name__ == "__main__":
    main()
