#!/usr/bin/env python3
"""Compare private nt1 SSH/VLESS/Naive configs without changing the active VPN."""
import argparse
import collections
import concurrent.futures
import copy
import datetime
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time

TARGETS = {
    "gstatic": ("https://www.gstatic.com/generate_204", 204),
    "chatgpt": ("https://chatgpt.com/cdn-cgi/trace", 200),
    "openai-api": ("https://api.openai.com/v1/models", 401),
}


def probe(route, port, target, round_no):
    url, expected = TARGETS[target]
    started = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    result = subprocess.run(
        ["curl", "--silent", "--show-error", "--noproxy", "", "--proxy",
         f"http://127.0.0.1:{port}", "--connect-timeout", "5", "--max-time", "12",
         "--output", "/dev/null", "--write-out", "%{json}", url],
        capture_output=True, text=True, timeout=15,
    )
    metrics = json.loads(result.stdout)
    return {
        "time": started, "round": round_no, "route": route, "target": target,
        "exit": result.returncode, "error": result.stderr.strip(),
        "expected_status": expected,
        **{key: metrics[key] for key in
           ["http_code", "time_appconnect", "time_starttransfer", "time_total"]},
    }


def summarize(rows):
    summary = []
    for route in ("ssh", "vless", "naive"):
        for target in TARGETS:
            group = [row for row in rows if row["route"] == route and row["target"] == target]
            good = [row for row in group if row["exit"] == 0 and row["http_code"]]
            times = sorted(row["time_total"] for row in good)
            summary.append({
                "route": route, "target": target, "requests": len(group),
                "transport_ok": len(good),
                "expected_status_ok": sum(row["http_code"] == row["expected_status"] for row in good),
                "status_counts": dict(collections.Counter(str(row["http_code"]) for row in group)),
                "median_seconds": round(times[len(times) // 2], 3) if times else None,
                "p95_seconds": round(times[min(len(times) - 1, int(len(times) * .95))], 3) if times else None,
                "max_seconds": round(max(times), 3) if times else None,
            })
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=60)
    parser.add_argument("--interval", type=float, default=10)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.rounds < 1 or args.interval < 0:
        parser.error("rounds must be positive and interval nonnegative")
    os.umask(0o077)
    args.output.mkdir(parents=True, exist_ok=True)
    home = Path.home()
    base = json.loads((home / ".config/sing-box/config-all-proxy.json").read_text())
    processes, logs, ports, rows = [], [], {}, []
    with tempfile.TemporaryDirectory(prefix="nt1-proxy-check-") as temporary:
        try:
            for index, route in enumerate(("ssh", "vless", "naive")):
                work = Path(temporary) / route
                work.mkdir()
                config = copy.deepcopy(base)
                outbound = json.loads((home / f".local/share/nt1-{route}.json").read_text())["outbounds"]
                tags = [item["tag"] for item in outbound]
                config["outbounds"] += outbound + [{
                    "type": "selector", "tag": "proxy", "outbounds": tags, "default": tags[0],
                }]
                # Ask the OS for an unused port; fail rather than touching an active listener.
                config["inbounds"][0]["listen_port"] = 0
                config["experimental"]["clash_api"]["external_controller"] = ""
                config["experimental"]["cache_file"]["path"] = str(work / "cache.db")
                config["log"]["level"] = "info"
                path = work / "config.json"
                path.write_text(json.dumps(config))
                log_path = args.output / f"{route}.log"
                log = log_path.open("w")
                logs.append(log)
                process = subprocess.Popen(
                    ["sing-box", "-D", str(work), "-c", str(path), "run"], stdout=log, stderr=log,
                )
                processes.append(process)
                for _ in range(200):
                    if process.poll() is not None:
                        raise RuntimeError(f"{route} stopped; inspect {log_path}")
                    text = log_path.read_text()
                    # Tied to sing-box's startup log format; use its Clash API if that changes.
                    marker = "tcp server started at 127.0.0.1:"
                    if marker in text:
                        # Color codes can follow the port; strip them before parsing.
                        port = int(text.split(marker, 1)[1].splitlines()[0].split("\x1b", 1)[0])
                        with socket.create_connection(("127.0.0.1", port), timeout=1):
                            ports[route] = port
                        break
                    time.sleep(.25)
                else:
                    raise RuntimeError(f"{route} startup timed out; inspect {log_path}")
                print(f"{route} ready on isolated port {ports[route]}", flush=True)
            started = time.monotonic()
            with (args.output / "results.jsonl").open("w") as output, \
                    concurrent.futures.ThreadPoolExecutor(max_workers=9) as pool:
                for round_no in range(1, args.rounds + 1):
                    time.sleep(max(0, started + (round_no - 1) * args.interval - time.monotonic()))
                    futures = [pool.submit(probe, route, port, target, round_no)
                               for route, port in ports.items() for target in TARGETS]
                    for future in concurrent.futures.as_completed(futures):
                        row = future.result()
                        rows.append(row)
                        output.write(json.dumps(row) + "\n")
                        output.flush()
                        print(f"round={round_no:02} {row['route']:5} {row['target']:10} "
                              f"http={row['http_code']} exit={row['exit']} "
                              f"total={row['time_total']:.3f}s", flush=True)
                    (args.output / "summary.json").write_text(json.dumps(summarize(rows), indent=2))
            print(json.dumps(summarize(rows), indent=2), flush=True)
        finally:
            for process in processes:
                process.terminate()
            for process in processes:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            for log in logs:
                log.close()


if __name__ == "__main__":
    main()
