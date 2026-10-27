#!/usr/bin/env python3
"""Build the isolated Discord service config from a generated Linux profile."""
import copy
import json
import sys


def make_config(profile):
    outbounds = {o["tag"]: o for o in profile["outbounds"]}
    chain = copy.deepcopy(outbounds["cherry-vless-via-naive"])
    carrier = copy.deepcopy(outbounds[chain["detour"]])
    if chain["type"] != "vless" or carrier["type"] != "naive" or carrier.get("detour"):
        raise ValueError("Expected the directly dialed Cherry Naïve carrier")
    # Bootstrap only the carrier hostname through host DNS, not through the
    # tunnel it is needed to establish. Application DNS stays inside VLESS.
    carrier["domain_resolver"] = "bootstrap"
    return {
        "log": {"level": "warn"},
        "dns": {"servers": [
            {"type": "local", "tag": "bootstrap"},
            {"type": "udp", "tag": "dns", "server": "1.1.1.1", "detour": chain["tag"]},
        ], "final": "dns"},
        "inbounds": [{
            "type": "tun", "tag": "discord", "interface_name": "dvpn0",
            "netns": "discord-vpn", "address": ["172.31.255.1/30", "fdfe:dcba:9876::1/126"],
            "mtu": 1500, "auto_route": True, "strict_route": True, "dns_mode": "disabled",
        }],
        "outbounds": [chain, carrier],
        # The core and its outbound sockets stay in the host namespace; only the
        # TUN/routes live in discord-vpn. No veth, host NAT or host route changes.
        "route": {"rules": [{"port": 53, "action": "hijack-dns"}], "final": chain["tag"]},
    }


if __name__ == "__main__":
    try:
        print(json.dumps(make_config(json.load(sys.stdin)), indent=2))
    except (KeyError, ValueError, TypeError):
        sys.exit("Cannot build Discord config; generate the Cherry profiles first.")
