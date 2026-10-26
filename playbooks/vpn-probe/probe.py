#!/usr/bin/env python3
"""Observe direct controls and explicit loopback proxies; never switch or buy anything."""
import argparse
import concurrent.futures
import contextlib
import datetime
import itertools
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import urlsplit

TARGETS = (
    ("gstatic", "https://www.gstatic.com/generate_204", 204),
    ("cloudflare", "https://www.cloudflare.com/cdn-cgi/trace", 200),
)


def proxy_argument(value):
    name, separator, address = value.partition("=")
    try:
        url = urlsplit(address)
        valid = (
            separator and re.fullmatch(r"[A-Za-z0-9_-]+", name)
            and url.scheme in {"http", "socks5h"}
            and url.hostname in {"127.0.0.1", "::1"} and url.port
            and not url.username and not url.password
            and not url.query and not url.fragment and url.path in {"", "/"}
        )
    except ValueError:
        valid = False
    if not valid:
        raise argparse.ArgumentTypeError("Use NAME=http://127.0.0.1:PORT or NAME=socks5h://127.0.0.1:PORT")
    return name, address


def https_argument(value):
    try:
        url = urlsplit(value)
        valid = url.scheme == "https" and url.hostname and not url.username and not url.password
    except ValueError:
        valid = False
    if not valid:
        raise argparse.ArgumentTypeError("Controls must be HTTPS URLs without credentials")
    return value


def request(url, proxy=None, expected=None):
    # Ignore inherited proxies and curlrc. Under a system TUN these controls still
    # follow OS routes: configure/test an explicit bypass before trusting them.
    env = {key: value for key, value in os.environ.items()
           if key.lower() not in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}}
    command = [
        "curl", "--disable", "--silent", "--show-error", "--ipv4",
        "--proxy", proxy or "", "--noproxy", "" if proxy else "*",
        "--connect-timeout", "5", "--max-time", "12", "--max-filesize", "1048576",
        "--output", "/dev/null", "--write-out", "%{json}", url,
    ]
    try:
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=15)
        metrics = json.loads(result.stdout)
        if not isinstance(metrics, dict):
            raise ValueError("Expected curl metrics object")
        status = int(metrics.get("http_code", 0))
        return {
            "ok": result.returncode == 0 and (status == expected if expected else 200 <= status < 400),
            "exit": result.returncode,
            "http_status": status,
            "seconds": metrics.get("time_total"),
        }
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        return {"ok": False, "exit": None, "http_status": 0, "seconds": None}


def classify(controls, checks, streak, threshold):
    if not all(check["ok"] for check in controls):
        # Even local outage vs blocked control URLs is ambiguous. Never count this
        # toward endpoint replacement; use independently reachable local controls.
        return "inconclusive_direct_controls", 0
    if all(check["ok"] for check in checks):
        return "healthy", 0
    if any(check["ok"] for check in checks):
        return "degraded_destination_or_path", 0
    streak += 1
    return ("suspected_path_failure" if streak >= threshold else "failing"), streak


def write_metrics(path, row):
    """Atomically publish the last completed round, never a partial scrape."""
    lines = [
        '# TYPE vpn_probe_timestamp_seconds gauge',
        f'vpn_probe_timestamp_seconds {datetime.datetime.fromisoformat(row["time"]).timestamp()}',
        '# TYPE vpn_probe_controls_ok gauge',
        f'vpn_probe_controls_ok {int(all(check["ok"] for check in row["controls"]))}',
        '# TYPE vpn_probe_success gauge',
    ]
    for name, result in row["proxies"].items():
        for target, check in result["checks"].items():
            lines.append(f'vpn_probe_success{{protocol="{name}",target="{target}"}} {int(check["ok"])}')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text("\n".join(lines) + "\n")
    temporary.chmod(0o644)
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proxy", action="append", required=True, type=proxy_argument)
    parser.add_argument("--control-url", action="append", required=True, type=https_argument,
                        help="Repeat for at least two HTTPS sites reachable directly from this ISP")
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--continuous", action="store_true", help="Run until stopped instead of limiting rounds")
    parser.add_argument("--interval", type=float, default=30)
    parser.add_argument("--failure-threshold", type=int, default=3)
    parser.add_argument("--output", type=Path, help="Append-only local JSONL observations")
    parser.add_argument("--metrics-output", type=Path, help="Atomically replaced Prometheus textfile")
    args = parser.parse_args()
    if args.rounds < 1 or args.interval < 0 or args.failure_threshold < 1:
        parser.error("rounds/threshold must be positive and interval nonnegative")
    if len(set(args.control_url)) < 2:
        parser.error("At least two distinct direct control URLs are required")
    proxies = dict(args.proxy)
    if len(proxies) != len(args.proxy):
        parser.error("Proxy names must be unique")

    if not args.output and not args.metrics_output:
        parser.error("At least one of --output or --metrics-output is required")
    os.umask(0o077)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    streaks = dict.fromkeys(proxies, 0)
    started = time.monotonic()
    with (args.output.open("a") if args.output else contextlib.nullcontext()) as output, concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        if args.output:
            args.output.chmod(0o600)
        rounds = itertools.count() if args.continuous else range(args.rounds)
        for round_no in rounds:
            time.sleep(max(0, started + round_no * args.interval - time.monotonic()))
            control_jobs = [pool.submit(request, url) for url in args.control_url]
            proxy_jobs = {
                name: [(target, pool.submit(request, url, proxy, expected))
                       for target, url, expected in TARGETS]
                for name, proxy in proxies.items()
            }
            controls = [job.result() for job in control_jobs]
            row = {"time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   "controls": controls, "proxies": {}}
            for name, jobs in proxy_jobs.items():
                checks = {target: job.result() for target, job in jobs}
                state, streaks[name] = classify(controls, list(checks.values()), streaks[name], args.failure_threshold)
                row["proxies"][name] = {"state": state, "failure_streak": streaks[name], "checks": checks}
            line = json.dumps(row)
            if output:
                output.write(line + "\n")
                output.flush()
            if args.metrics_output:
                write_metrics(args.metrics_output, row)
            print(line, flush=True)


if __name__ == "__main__":
    main()
