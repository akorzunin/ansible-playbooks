#!/usr/bin/env python3
"""Build the isolated Vesktop Wi-Fi VPN config from a generated Linux profile."""
import copy
import json
import sys


def make_config(profile):
    outbounds = {o["tag"]: o for o in profile["outbounds"]}
    outbound = copy.deepcopy(outbounds["cherry-vless"])
    if outbound["type"] != "vless" or outbound.get("detour"):
        raise ValueError("Expected the direct Cherry VLESS outbound")
    # 0x2024 is the main host sing-box TUN's bypass mark; keep it in sync
    # if that service's routing mark changes. No carrier or wired fallback.
    # Vision requires XUDP for UDP; plain UDP streams fail with flow mismatch.
    outbound.update(bind_interface="wlan0", routing_mark=0x2024,
                    domain_resolver="bootstrap", packet_encoding="xudp")
    return {
        "log": {"level": "warn"},
        "dns": {"servers": [
            {"type": "udp", "tag": "bootstrap", "server": "1.1.1.1",
             "bind_interface": "wlan0", "routing_mark": 0x2024},
            # DNS must not depend on the application's UDP/XUDP relay.
            {"type": "tcp", "tag": "dns", "server": "1.1.1.1", "detour": outbound["tag"]},
        ], "final": "dns",
            # The exit has no IPv6 egress; restore dual-stack only after
            # IPv6 TLS and UDP checks pass.
            "strategy": "ipv4_only"},
        "inbounds": [{
            "type": "tun", "tag": "discord", "interface_name": "dvpn0",
            "netns": "discord-vpn", "address": ["172.31.255.1/30", "fdfe:dcba:9876::1/126"],
            # Use userspace TCP inside this namespace on sing-box 1.14.
            # Recheck the replacement TUN stack when upgrading to 1.15.
            "mtu": 1500, "stack": "gvisor", "auto_route": True,
            "strict_route": True, "dns_mode": "disabled",
        }],
        "outbounds": [outbound],
        # The core/sockets stay in the host namespace; only TUN/routes live
        # in discord-vpn. No veth, host NAT or host route changes.
        "route": {"rules": [{"port": 53, "action": "hijack-dns"}], "final": outbound["tag"]},
    }


if __name__ == "__main__":
    try:
        print(json.dumps(make_config(json.load(sys.stdin)), indent=2))
    except (KeyError, ValueError, TypeError):
        sys.exit("Cannot build Discord config; generate the Cherry profiles first.")
