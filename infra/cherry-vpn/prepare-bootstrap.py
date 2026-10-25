#!/usr/bin/env python3
"""Persist the state-encryption secret and pre-pinned host identity in shared Vault."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent


def read_vault(path, password_file):
    result = subprocess.run(
        ["ansible-vault", "view", "--vault-password-file", str(password_file), str(path)],
        check=True, capture_output=True,
    )
    return json.loads(result.stdout)


def write_vault(path, password_file, data):
    encrypted = subprocess.run(
        ["ansible-vault", "encrypt", "--vault-password-file", str(password_file), "--output", "-"],
        input=json.dumps(data).encode(), check=True, capture_output=True,
    ).stdout
    if not encrypted.startswith(b"$ANSIBLE_VAULT;"):
        raise ValueError("Expected Vault ciphertext")
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
        try:
            temporary.write(encrypted)
            temporary.flush()
            os.fsync(temporary.fileno())
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)


def host_key():
    # ssh-keygen needs a file: its temporary private key is mode 0600 inside a
    # mode-0700 directory, removed immediately. Only Vault ciphertext persists.
    with tempfile.TemporaryDirectory(prefix="vpn-host-key-") as directory:
        path = Path(directory) / "host"
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "vpn-dyn1-host", "-f", str(path)],
            check=True, capture_output=True,
        )
        return {"private": path.read_text(), "public": path.with_suffix(".pub").read_text().strip()}


def fingerprint(public):
    parts = public.split()
    if len(parts) < 2 or parts[0] != "ssh-ed25519":
        raise ValueError("Expected an Ed25519 public key")
    return "SHA256:" + base64.b64encode(hashlib.sha256(base64.b64decode(parts[1], validate=True)).digest()).decode().rstrip("=")


def prepare(path, password_file, rotate=False):
    if path.is_symlink():
        raise ValueError("Use the actual shared Vault path, not a symlink")
    data = read_vault(path, password_file)
    existing = data.get("vpn_bootstrap")
    if existing is not None:
        # Never replace the encryption secret: old states/plans must stay readable.
        if (not isinstance(existing.get("state_passphrase"), str)
                or len(existing["state_passphrase"]) < 32):
            raise ValueError("Invalid existing encryption secret; refusing regeneration")
        fingerprint(existing["ssh_host_key"]["public"])
        if not rotate:
            return existing, False
    else:
        existing = {"state_passphrase": secrets.token_urlsafe(48)}
    existing["ssh_host_key"] = host_key()
    data["vpn_bootstrap"] = existing
    write_vault(path, password_file, data)
    return existing, True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, default=ROOT / "secrets.vault.yaml")
    parser.add_argument("--vault-password-file", type=Path, default=ROOT.parent.parent / ".ansible_pass")
    parser.add_argument("--rotate-host-key", action="store_true",
                        help="Prepare a fresh host key for a deliberate replacement; retain the encryption secret")
    args = parser.parse_args()
    try:
        bootstrap, changed = prepare(args.vault, args.vault_password_file, args.rotate_host_key)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError):
        parser.exit(1, "Bootstrap preparation failed; check shared Vault inputs locally. No secrets were printed.\n")
    print("Shared bootstrap credentials updated." if changed else "Existing bootstrap credentials retained.")
    print("Expected host fingerprint:", fingerprint(bootstrap["ssh_host_key"]["public"]))
