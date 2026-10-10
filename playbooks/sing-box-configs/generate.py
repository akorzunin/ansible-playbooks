#!/usr/bin/env python3
"""Render profiles from platform settings and decrypted Vault JSON on stdin."""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent
DOMAIN = "configs.akorz.duckdns.org"
ORDERS = {
    "android": ["naive", "ssh", "vless"],
    "windows": ["vless", "naive", "ssh"],
    "linux": ["vless", "naive", "ssh"],
}


def private_write(path, content):
    """Atomic replacement without exposing credentials through default permissions."""
    with tempfile.NamedTemporaryFile(dir=path.parent, mode="w", delete=False) as tmp:
        temporary = Path(tmp.name)
        try:
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def make_profile(base, connections, order):
    profile = copy.deepcopy(base)
    tags = [connections[kind]["tag"] for kind in order]
    profile["outbounds"] = [
        {"type": "selector", "tag": "proxy", "outbounds": ["auto", *tags],
         "default": "auto", "interrupt_exist_connections": True},
        # URLTest is latency-based, not ordered failover; the order only seeds selection.
        {"type": "urltest", "tag": "auto", "outbounds": tags,
         "url": "https://www.gstatic.com/generate_204", "interval": "3m",
         "tolerance": 50, "interrupt_exist_connections": True},
        *[copy.deepcopy(connections[kind]) for kind in order],
        {"type": "direct", "tag": "direct"},
    ]
    route = profile.setdefault("route", {})
    # TUN connections initially contain IPs, so sniff TLS SNI before matching
    # DuckDNS names. Keep this bypass before the catch-all UDP proxy rule.
    # Sniffing cannot identify IP-only/ECH traffic; add DNS mapping or IP rules
    # if those connections also need a guaranteed bypass.
    rules = [
        {"action": "sniff"},
        {"domain_suffix": ["duckdns.org"], "action": "route", "outbound": "direct"},
        *[r for r in route.get("rules", []) if r.get("action") != "sniff"],
    ]
    route["rules"] = rules
    for rule in rules:
        if rule.get("network") == "udp":
            rule["outbound"] = connections["vless"]["tag"]
    route["final"] = "proxy"
    for rule_set in route.get("rule_set", []):
        if rule_set.get("type") == "remote":
            # No detour means direct dialing. An empty {} instead selects the
            # deprecated implicit client; detouring to an empty direct is rejected.
            rule_set["http_client"] = {"engine": "go"}
    experimental = profile.setdefault("experimental", {})
    experimental["clash_api"] = {"external_controller": "127.0.0.1:9091"}
    # Do not restore an old selector choice after publishing a new default.
    experimental.pop("cache_file", None)
    return profile


def generate(private_dir, connections, tokens):
    if set(connections) != {"vless", "naive", "ssh"}:
        raise ValueError("Vault must contain vless, naive and ssh connections")
    for kind, outbound in connections.items():
        if outbound.get("type") != kind:
            raise ValueError(f"Connection {kind} must have type {kind}")
    tags = [o["tag"] for o in connections.values()]
    if len(set(tags)) != 3 or set(tags) & {"auto", "proxy", "direct"}:
        raise ValueError("Connection tags must be unique and cannot be auto/proxy/direct")
    # Tokens are shared deployment state, never generated on a fresh controller.
    if set(tokens) != set(ORDERS):
        raise ValueError("Vault must contain tokens for all three platforms")
    for platform, token in tokens.items():
        if not isinstance(token, str) or len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
            raise ValueError(f"Invalid token for {platform}")
    private_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_dir.chmod(0o700)

    # Validate all platforms before replacing any published local artifacts.
    with tempfile.TemporaryDirectory(dir=private_dir) as work:
        rendered = {}
        for platform, order in ORDERS.items():
            base = json.loads((ROOT / "templates" / f"{platform}.json").read_text())
            rendered[platform] = json.dumps(make_profile(base, connections, order), indent=2) + "\n"
            candidate = Path(work) / f"{platform}.json"
            private_write(candidate, rendered[platform])
            # Check with the installed core; platform-specific runtime behavior still
            # needs testing on the target OS and matching client core versions.
            subprocess.run(["sing-box", "check", "-c", str(candidate)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    private_write(private_dir / "tokens.json", json.dumps(tokens, indent=2) + "\n")
    for platform, content in rendered.items():
        private_write(private_dir / f"{platform}.json", content)
    urls = {p: f"https://{DOMAIN}/{tokens[p]}/{p}.json" for p in ORDERS}
    private_write(private_dir / "urls.json", json.dumps(urls, indent=2) + "\n")
    imports = {p: f"sing-box://import-remote-profile?url={quote(url, safe='')}#nt1-{p}"
               for p, url in urls.items()}
    private_write(private_dir / "import-links.json", json.dumps(imports, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-dir", type=Path, default=ROOT / "private")
    args = parser.parse_args()
    try:
        data = json.load(sys.stdin)["sing_box_secrets"]
        generate(args.private_dir, data["connections"], data["tokens"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError):
        # Input/core errors can contain credentials. Never echo them to deployment logs.
        parser.exit(1, "Profile generation failed; check Vault inputs and sing-box locally.\n")
    print(f"Validated profiles and stable enrollment URLs saved in {args.private_dir}")
