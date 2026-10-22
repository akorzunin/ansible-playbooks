#!/usr/bin/env python3
"""Read the public catalogue without credentials, orders or other API mutations."""
import json
import urllib.error
import urllib.request

PLANS = {"B1-1-1gb-20s-shared", "B2-1-1gb-20s-shared"}


def main():
    try:
        with urllib.request.urlopen("https://api.cherryservers.com/v1/plans", timeout=30) as response:
            plans = json.load(response)
        for plan in plans:
            if plan["slug"] not in PLANS:
                continue
            rates = [rate for rate in plan["pricing"] if rate["unit"].lower() == "hourly"]
            print(json.dumps({
                "plan": plan["slug"],
                "hourly_compute_quotes": rates,
                "bandwidth": plan["specs"]["bandwidth"]["name"],
                "regions": [
                    {"region": region["slug"], "stock": region["stock_qty"]}
                    for region in plan["available_regions"]
                ],
            }, indent=2))
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError):
        raise SystemExit("Cannot read the catalogue. No resources were ordered.") from None


if __name__ == "__main__":
    main()
