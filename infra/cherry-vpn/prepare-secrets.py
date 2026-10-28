#!/usr/bin/env python3
"""Create shared VPN credentials directly in Ansible Vault, refusing replacement."""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import subprocess
import uuid

ROOT = Path(__file__).resolve().parent


def credentials():
    private = subprocess.run(
        ["openssl", "genpkey", "-algorithm", "X25519", "-outform", "DER"],
        check=True, capture_output=True,
    ).stdout
    public = subprocess.run(
        ["openssl", "pkey", "-inform", "DER", "-pubout", "-outform", "DER"],
        input=private, check=True, capture_output=True,
    ).stdout
    # RFC 8410 DER wrappers for raw 32-byte X25519 keys; fail on a format change.
    if (len(private) != 48 or private[:16].hex() != "302e020100300506032b656e04220420"
            or len(public) != 44 or public[:12].hex() != "302a300506032b656e032100"):
        raise ValueError("Unexpected OpenSSL X25519 format")
    encode = lambda key: base64.urlsafe_b64encode(key).decode().rstrip("=")
    return {
        "naive_username": "vpn",
        "naive_password": secrets.token_urlsafe(32),
        "vless_uuid": str(uuid.uuid4()),
        "reality_private_key": encode(private[-32:]),
        "reality_public_key": encode(public[-32:]),
        "reality_short_id": secrets.token_hex(8),
    }


def prepare(output, password_file, *, hysteria2=False):
    if output.exists() or output.is_symlink():
        raise FileExistsError("Refusing to replace shared credentials")
    data = ({"vpn_node_hysteria2_password": secrets.token_urlsafe(32)} if hysteria2
            else {"vpn_node_credentials": credentials()})
    payload = json.dumps(data).encode()
    result = subprocess.run(
        ["ansible-vault", "encrypt", "--vault-password-file", str(password_file), "--output", "-"],
        input=payload, check=True, capture_output=True,
    )
    if not result.stdout.startswith(b"$ANSIBLE_VAULT;"):
        raise ValueError("Vault did not return encrypted content")
    # Exclusive creation also refuses a race with another controller or a symlink.
    with os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as vault:
        vault.write(result.stdout)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hysteria2", action="store_true", help="Prepare only the dedicated Hysteria 2 Vault")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--vault-password-file", type=Path, default=ROOT.parent.parent / ".ansible_pass")
    args = parser.parse_args()
    try:
        output = args.output or ROOT / ("hysteria2.vault.yaml" if args.hysteria2 else "secrets.vault.yaml")
        prepare(output, args.vault_password_file, hysteria2=args.hysteria2)
    except (OSError, ValueError, subprocess.CalledProcessError):
        parser.exit(1, "Credential preparation failed. Existing files are never replaced; check paths and Vault access.\n")
    print(f"Encrypted shared credentials created: {output}")
