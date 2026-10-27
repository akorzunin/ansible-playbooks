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
    "android": ["ssh", "vless", "naive"],
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


def make_profile(base, connections, order, extra_outbounds=()):
    profile = copy.deepcopy(base)
    tags = [connections[kind]["tag"] for kind in order]
    tags.extend(outbound["tag"] for outbound in extra_outbounds
                if outbound["tag"] != "workstation-hop")
    profile["outbounds"] = [
        {"type": "selector", "tag": "proxy", "outbounds": tags,
         "default": tags[0], "interrupt_exist_connections": True},
        *[copy.deepcopy(connections[kind]) for kind in order],
        *copy.deepcopy(extra_outbounds),
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
        if rule.get("network") == "udp" and rule.get("action") == "route":
            rule["outbound"] = "proxy"
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


def generate(private_dir, connections, tokens, extra_outbounds=()):
    if set(connections) != {"vless", "naive", "ssh"}:
        raise ValueError("Vault must contain vless, naive and ssh connections")
    for kind, outbound in connections.items():
        if outbound.get("type") != kind:
            raise ValueError(f"Connection {kind} must have type {kind}")
    if not isinstance(extra_outbounds, (list, tuple)) or any(
        not isinstance(outbound, dict) or not isinstance(outbound.get("type"), str)
        or not outbound["type"] for outbound in extra_outbounds
    ):
        raise ValueError("Extra outbounds must be a list of sing-box outbound objects")
    extra_outbounds = list(extra_outbounds)
    # VLESS relays UDP inside a TCP stream even when its Naïve carrier cannot
    # relay UDP itself. Derive trial-node chains so credentials cannot drift.
    for outbound in list(extra_outbounds):
        tag = outbound.get("tag")
        if outbound["type"] == "vless" and isinstance(tag, str) and tag.endswith("-vless"):
            carrier = tag.removesuffix("-vless") + "-naive"
            if not outbound.get("detour") and any(
                o["type"] == "naive" and o.get("tag") == carrier for o in extra_outbounds
            ):
                extra_outbounds.append({**copy.deepcopy(outbound), "tag": tag + "-via-naive", "detour": carrier})
    hops = [o for o in extra_outbounds if o.get("tag") == "workstation-hop"]
    if hops:
        if any(o["type"] != "ssh" for o in hops):
            raise ValueError("workstation-hop must be an SSH outbound")
        # Keep the intermediate hop private to chained SSH outbounds, not selectable.
        for outbound in [*connections.values(), *extra_outbounds]:
            if (outbound["type"] == "ssh" and outbound.get("tag") != "workstation-hop"
                    and not outbound.get("detour")):
                chained = copy.deepcopy(outbound)
                chained["tag"] = f"{outbound.get('tag', '')}-via-workstation"
                chained["detour"] = "workstation-hop"
                extra_outbounds.append(chained)
    tags = [o.get("tag") for o in [*connections.values(), *extra_outbounds]]
    if any(not isinstance(tag, str) or not tag for tag in tags):
        raise ValueError("Connection tags must be nonempty strings")
    if len(set(tags)) != len(tags) or set(tags) & {"auto", "proxy", "direct"}:
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
            rendered[platform] = json.dumps(make_profile(base, connections, order, extra_outbounds), indent=2) + "\n"
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
    parser.add_argument("--extra-outbounds-file", type=Path,
                        help="Private JSON list exported by the vpn_node role")
    args = parser.parse_args()
    try:
        data = json.load(sys.stdin)["sing_box_secrets"]
        extra = data.get("extra_outbounds", [])
        if args.extra_outbounds_file:
            extra = extra + json.loads(args.extra_outbounds_file.read_text())
        generate(args.private_dir, data["connections"], data["tokens"], extra)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError):
        # Input/core errors can contain credentials. Never echo them to deployment logs.
        parser.exit(1, "Profile generation failed; check Vault inputs and sing-box locally.\n")
    print(f"Validated profiles and stable enrollment URLs saved in {args.private_dir}")
