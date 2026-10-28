#!/usr/bin/env python3
"""Own only inet vpn_reference. Native host INPUT, never Docker port publishing."""
import argparse
import subprocess

import endpoint


def rules(sources, exists):
    # Source strings are validated IPv4 /32s, not interpolated arbitrary nft syntax.
    addresses = []
    for source in sources:
        network = endpoint.ipaddress.IPv4Network(source, strict=True)
        if network.prefixlen != 32:
            raise ValueError("host-source-required")
        # Plain ipv4_addr sets take host literals, not even /32 prefix elements.
        addresses.append(str(network.network_address))
    prefix = "delete table inet vpn_reference\n" if exists else ""
    return prefix + """table inet vpn_reference {
    set sources { type ipv4_addr; elements = { %s }; }
    chain input {
        type filter hook input priority -10; policy accept;
        tcp dport 9443 ip saddr @sources counter return
        udp dport 9444 ip saddr @sources counter return
        tcp dport 9443 counter drop
        udp dport 9444 counter drop
    }
}
""" % ", ".join(addresses)


def nft(*args, **kwargs):
    return subprocess.run(["/usr/sbin/nft", *args], capture_output=True, timeout=5, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["apply", "remove"])
    parser.add_argument("--config")
    args = parser.parse_args()
    try:
        listed = nft("list", "tables", check=True).stdout.decode()
        exists = "table inet vpn_reference" in listed.splitlines()
        if args.action == "remove":
            if exists:
                nft("delete", "table", "inet", "vpn_reference", check=True)
        else:
            config = endpoint.validate(endpoint.private_json(args.config))
            # One atomic nft transaction. Failure leaves the previous guard intact.
            nft("-f", "-", input=rules(config["sources"], exists).encode(), check=True)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        parser.exit(1, "reference firewall failed (details suppressed)\n")


if __name__ == "__main__":
    main()
