#!/usr/bin/env python3
"""Preview or replace the monitor allowlist from the shared encrypted sing-box source."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import yaml

from generate import ROUTING_OVERRIDES

STACK = Path(__file__).resolve().parent
ROOT = STACK.parents[1]
SUPPORTED_TYPES = {
    "ssh", "naive", "vless", "vmess", "trojan", "shadowsocks",
    "hysteria", "hysteria2", "tuic", "socks", "http",
}
NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,47}")


def discover_servers(secrets, nodes=()):
    if not isinstance(nodes, (list, tuple)) or any(not isinstance(node, str) for node in nodes):
        raise ValueError("Nodes must be a list of names")
    outbounds = [*secrets.get("connections", {}).values(), *secrets.get("extra_outbounds", [])]
    tags = [outbound["tag"] for outbound in outbounds]
    if any(not isinstance(tag, str) or not tag for tag in tags) or len(tags) != len(set(tags)):
        raise ValueError("Source tags must be unique nonempty strings")
    servers = {}
    for outbound in outbounds:
        kind, tag = outbound["type"], outbound["tag"]
        if kind not in SUPPORTED_TYPES or tag == "workstation-hop" or ROUTING_OVERRIDES.intersection(outbound):
            continue
        # Published node tags are <node>-<type>; legacy bare types use 'default'.
        if tag == kind:
            node = "default"
        elif tag.endswith("-" + kind):
            node = tag[:-(len(kind) + 1)]
        else:
            continue
        if not NAME.fullmatch(node):
            raise ValueError("Invalid monitor server name")
        if nodes and node not in nodes:
            continue
        servers.setdefault(node, []).append({"name": kind, "outbound_tag": tag, "udp": False})
    if not servers or set(nodes) - servers.keys():
        raise ValueError("No standalone routes for the requested nodes")
    if sum(map(len, servers.values())) > 64:
        raise ValueError("Monitor supports at most 64 routes; select fewer nodes")
    # UDP stays opt-in: an outbound alone does not establish endpoint/server support.
    return [{"name": node, "protocols": sorted(protocols, key=lambda p: p["name"])}
            for node, protocols in sorted(servers.items())]


def update_settings(path, servers):
    settings = yaml.safe_load(path.read_text())
    if settings["servers"] == servers:
        return False
    settings["servers"] = servers
    content = yaml.safe_dump(settings, sort_keys=False)
    # Atomic replacement; do not leave a truncated config after an interrupted write.
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            temporary.chmod(path.stat().st_mode & 0o777)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-file", type=Path, default=STACK.parent / "sing-box-configs/secrets.vault.yaml")
    parser.add_argument("--vault-password-file", type=Path, default=ROOT / ".ansible_pass")
    parser.add_argument("--config", type=Path, default=STACK / "config.yaml")
    parser.add_argument("--node", action="append", default=[], help="Include only this node; repeat for multiple nodes")
    parser.add_argument("--write", action="store_true", help="Replace servers in config.yaml; default only previews YAML")
    parser.add_argument("--stdin", action="store_true", help="Read decrypted JSON with sing_box_secrets and optional nodes from stdin")
    args = parser.parse_args()
    try:
        if args.stdin:
            data = json.load(sys.stdin)
        else:
            result = subprocess.run([
                "ansible-vault", "view", "--vault-password-file", str(args.vault_password_file), str(args.vault_file),
            ], check=True, capture_output=True)
            data = yaml.safe_load(result.stdout)
        servers = discover_servers(data["sing_box_secrets"], data.get("nodes", args.node))
        if args.write:
            changed = update_settings(args.config, servers)
            print("Monitor servers updated." if changed else "Monitor servers unchanged.")
        else:
            print(yaml.safe_dump({"servers": servers}, sort_keys=False), end="")
    except (OSError, ValueError, KeyError, TypeError, AttributeError, yaml.YAMLError, subprocess.SubprocessError):
        # Vault/parser failures may contain secrets; never print their details or input.
        parser.exit(1, "Server prefill failed; check Vault access, node names and settings locally. No credentials were printed.\n")


if __name__ == "__main__":
    main()
