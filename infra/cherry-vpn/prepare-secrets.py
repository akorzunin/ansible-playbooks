#!/usr/bin/env python3
"""Create shared VPN credentials directly in Ansible Vault, refusing replacement."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent


spec = importlib.util.spec_from_file_location("vpn_credentials", ROOT.parent.parent / "roles/vpn_node/files/credentials.py")
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)
credentials = shared.credentials


def prepare(output, password_file):
    if output.exists() or output.is_symlink():
        raise FileExistsError("Refusing to replace shared credentials")
    data = {"vpn_node_credentials": credentials()}
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
    parser.add_argument("--output", type=Path)
    parser.add_argument("--vault-password-file", type=Path, default=ROOT.parent.parent / ".ansible_pass")
    args = parser.parse_args()
    try:
        output = args.output or ROOT / "secrets.vault.yaml"
        prepare(output, args.vault_password_file)
    except (OSError, ValueError, subprocess.CalledProcessError):
        parser.exit(1, "Credential preparation failed. Existing files are never replaced; check paths and Vault access.\n")
    print(f"Encrypted shared credentials created: {output}")
