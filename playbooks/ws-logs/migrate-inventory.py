#!/usr/bin/env python3
"""One-time, local-only merge of the old monitoring overlay into shared hosts."""

import argparse
import os
from pathlib import Path
import re
import tempfile

import yaml


ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hosts", type=Path, default=ROOT / "hosts")
    parser.add_argument("--overlay", type=Path, default=ROOT / "monitoring.inventory.yml")
    args = parser.parse_args()
    try:
        # Resolve the Dropbox symlink; atomic replacement must not replace the link itself.
        hosts = args.hosts.resolve(strict=True)
        original = hosts.read_text()
        overlay = args.overlay.read_text()
        # BaseLoader inspects structure without decrypting or rewriting !vault scalars.
        old_groups = yaml.load(original, Loader=yaml.BaseLoader)
        new_groups = yaml.load(overlay, Loader=yaml.BaseLoader)
        if not isinstance(old_groups, dict) or not isinstance(new_groups, dict):
            parser.exit(1, "Both inventories must be YAML group mappings; no files changed.\n")
        # Remove document markers before appending, retaining comments/anchors/ciphertext.
        overlay = re.sub(r"(?m)^(?:---|\.\.\.)[ \t]*(?:#.*)?(?:\n|$)", "", overlay)
        # SSH and monitoring blocks used identical markers when stored in separate files.
        overlay = re.sub(r"(?m)^( *# (?:BEGIN|END) ANSIBLE )BOOTSTRAP( [^\n]+)$",
                         r"\1MONITORING\2", overlay)
        block = "# BEGIN MIGRATED MONITORING INVENTORY\n" + overlay.rstrip() + "\n# END MIGRATED MONITORING INVENTORY\n"
        if block in original:
            print("Monitoring inventory is already merged; no files changed.")
            return
        # Append-only to preserve Vault text/comments; overlapping root groups need a manual merge.
        if old_groups.keys() & new_groups.keys():
            parser.exit(1, "Overlapping top-level groups; merge them manually without duplicate YAML keys. No files changed.\n")
        if not re.search(r"(?m)^\S[^\n]*:\s*$", original):
            parser.exit(1, "Use a block-style hosts inventory before appending groups; no files changed.\n")
        merged = original + "\n\n" + block
        yaml.load(merged, Loader=yaml.BaseLoader)  # Reject anchor collisions before writing.
        backup = hosts.with_name(hosts.name + ".monitoring-backup~")
        with os.fdopen(os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
            stream.write(original)
        # One active controller only; Dropbox cannot lock concurrent inventory edits.
        pending = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=hosts.parent, delete=False) as stream:
                pending = Path(stream.name)
                stream.write(merged)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(pending, hosts)
        finally:
            if pending is not None:
                pending.unlink(missing_ok=True)
        print(f"Merged monitoring into {args.hosts}; backup: {backup}")
        print("Use only -i hosts now. The old overlay was left untouched for recovery; archive it after verification.")
    except yaml.YAMLError:
        parser.exit(1, "Invalid YAML inventory; no inventory files changed.\n")
    except OSError as error:
        parser.exit(1, f"Cannot migrate inventory: {error}\n")


if __name__ == "__main__":
    main()
