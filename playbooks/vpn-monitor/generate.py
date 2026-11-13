#!/usr/bin/env python3
"""Resolve the monitor's explicit route allowlist from decrypted profile Vault JSON."""
import copy
import json
import sys


# The monitor accepts only standalone outbounds, not profile routing/chains.
ROUTING_OVERRIDES = {"detour", "domain_resolver", "network_strategy", "bind_interface", "routing_mark"}


def make_config(settings, secrets):
    config = copy.deepcopy(settings)
    outbounds = [*secrets.get("connections", {}).values(), *secrets.get("extra_outbounds", [])]
    for server in config["servers"]:
        for protocol in server["protocols"]:
            tag = protocol.pop("outbound_tag")
            matches = [outbound for outbound in outbounds if outbound.get("tag") == tag]
            if len(matches) != 1:
                raise ValueError("Each monitored tag must resolve to exactly one Vault outbound")
            outbound = copy.deepcopy(matches[0])
            if ROUTING_OVERRIDES.intersection(outbound):
                raise ValueError("Monitor routes must be standalone outbounds without routing overrides")
            # Tags belong to the profile graph; the monitor builds its own isolated graph.
            outbound.pop("tag", None)
            protocol["outbound"] = outbound
    return config


if __name__ == "__main__":
    try:
        data = json.load(sys.stdin)
        config = make_config(data["settings"], data["sing_box_secrets"])
    except (ValueError, KeyError, TypeError, AttributeError):
        # Never print input or exception details: they can contain outbound credentials.
        sys.exit("Monitor config generation failed; check settings and shared Vault outbounds.")
    print(json.dumps(config))
