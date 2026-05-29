#!/usr/bin/env python3
import argparse
import base64
import json


def generate_config(server_ip, key, host_port=21116, relay_port=21117, api_port=21118):
    config = {
        "host": f"{server_ip}:{host_port}",
        "relay": f"{server_ip}:{relay_port}",
        "api": f"http://{server_ip}:{api_port}",
        "key": key,
    }
    json_str = json.dumps(config, separators=(",", ":"))
    encoded = base64.b64encode(json_str.encode()).decode()[::-1]
    return config, encoded


def main():
    parser = argparse.ArgumentParser(description="Generate RustDesk config string")
    parser.add_argument("server_ip", help="RustDesk server IP address")
    parser.add_argument("key", help="Secret key")
    parser.add_argument(
        "--host-port",
        type=int,
        default=916,
        help="Rendezvous server port (default: 916)",
    )
    parser.add_argument(
        "--relay-port", type=int, default=917, help="Relay port (default: 917)"
    )
    parser.add_argument(
        "--api-port", type=int, default=918, help="API port (default: 918)"
    )
    args = parser.parse_args()

    config, encoded = generate_config(
        args.server_ip, args.key, args.host_port, args.relay_port, args.api_port
    )

    print("=== Config ===")
    print(json.dumps(config, indent=2))
    print("\n=== Encoded String ===")
    print(encoded)


if __name__ == "__main__":
    main()
