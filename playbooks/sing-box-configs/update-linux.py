#!/usr/bin/env python3
"""Fetch a remote profile directly, validate it, and retain the last working config."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request

MAX_PROFILE_BYTES = 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Remote profile redirects are not allowed")


def download(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Remote profile requires an HTTPS URL without userinfo")
    # Ignore HTTP(S)_PROXY: recovery must work when sing-box itself is broken.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(url, timeout=30) as response:
        content = response.read(MAX_PROFILE_BYTES + 1)
    if len(content) > MAX_PROFILE_BYTES:
        raise ValueError("Remote profile is too large")
    profile = json.loads(content)
    if not isinstance(profile, dict) or not profile.get("outbounds") or not profile.get("route"):
        raise ValueError("Remote profile is incomplete")
    return (json.dumps(profile, indent=2) + "\n").encode()


def replace_config(target, content, metadata):
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as tmp:
        candidate = Path(tmp.name)
        try:
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
            os.chown(candidate, metadata.st_uid, metadata.st_gid)
            os.chmod(candidate, metadata.st_mode & 0o777)
            os.replace(candidate, target)
        finally:
            candidate.unlink(missing_ok=True)


def restart():
    subprocess.run(["systemctl", "restart", "sing-box.service"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    subprocess.run(["systemctl", "is-active", "--quiet", "sing-box.service"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def update(url_file, target):
    content = download(json.loads(url_file.read_text())["url"])
    old = target.read_bytes()
    if json.loads(old) == json.loads(content):
        print("Remote profile unchanged")
        return False
    metadata = target.stat()
    with tempfile.TemporaryDirectory(dir=target.parent, prefix=".remote-check-") as work:
        candidate = Path(work) / "config.json"
        candidate.write_bytes(content)
        candidate.chmod(0o600)
        subprocess.run(["sing-box", "check", "-c", str(candidate)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    replace_config(target, content, metadata)
    try:
        restart()
    except Exception:
        replace_config(target, old, metadata)
        restart()
        raise RuntimeError("New profile failed to start; previous configuration restored") from None
    print("Remote profile installed; sing-box restarted")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url-file", type=Path, default=Path("/etc/sing-box-profile.json"))
    parser.add_argument("--config", type=Path, default=Path("/etc/sing-box/config.json"))
    args = parser.parse_args()
    try:
        # Serialize timer and manual updates for this single installed profile.
        with args.config.with_name(".remote-update.lock").open("a") as lock:
            os.chmod(lock.name, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            update(args.url_file, args.config)
    except Exception:
        # HTTP and core errors can contain the enrollment URL or proxy credentials.
        parser.exit(1, "Remote profile update failed; last configuration retained/restored.\n")
