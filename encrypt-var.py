#!/usr/bin/env python3
"""Prompt for a secret and save it as an encrypted external variable."""

import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile

import yaml


ROOT = Path(__file__).resolve().parent


def update_variable(original, key, encrypted):
    document = yaml.compose(original, Loader=yaml.BaseLoader)
    if not isinstance(document, yaml.MappingNode) or document.flow_style:
        raise ValueError("External variables must be a block-style YAML mapping.")
    keys = [node.value for node, _ in document.value if isinstance(node, yaml.ScalarNode)]
    if len(keys) != len(document.value) or len(set(keys)) != len(keys):
        raise ValueError("External variables must have unique scalar keys.")
    for name, value in document.value:
        if name.value != key:
            continue
        if not isinstance(value, yaml.ScalarNode) or value.start_mark.index < name.end_mark.index:
            raise ValueError("Only a direct scalar value can be replaced, not a mapping, list or alias.")
        # Line-based replacement supports ordinary top-level entries, not explicit YAML keys.
        if name.start_mark.column != 0:
            raise ValueError("Use an ordinary top-level key: value entry.")
        lines = original.splitlines(keepends=True)
        end = value.end_mark.line + bool(value.end_mark.column)
        merged = "".join(lines[:name.start_mark.line]) + encrypted + "".join(lines[end:])
        break
    else:
        end = document.end_mark.index
        prefix = original[:end]
        merged = prefix + ("\n" if prefix and not prefix.endswith("\n") else "") + encrypted + original[end:]
    # Reject dangling aliases or any invalid result before touching the file.
    yaml.compose(merged, Loader=yaml.BaseLoader)
    return merged


def save_variable(path, password_file, key):
    # Resolve shared-file symlinks before atomic replacement; never replace the link.
    target = path.resolve(strict=True)
    original = target.read_text()
    # Validate before opening the editor so malformed input cannot discard a newly entered secret.
    update_variable(original, key, f"{key}: !vault |\n  validation-placeholder\n")
    with tempfile.TemporaryDirectory(prefix="ansible-var-") as directory:
        vault = Path(directory) / "value.vault"
        # Let Vault manage the editor and its temporary plaintext file, just like `vault create`.
        subprocess.run(
            ["ansible-vault", "create", "--vault-password-file", str(password_file), str(vault)],
            check=True,
        )
        encrypted = f"{key}: !vault |\n" + "".join(f"  {line}\n" for line in vault.read_text().splitlines())
    merged = update_variable(original, key, encrypted)
    pending = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=target.parent, delete=False) as stream:
            pending = Path(stream.name)
            stream.write(merged)
            stream.flush()
            os.fsync(stream.fileno())
        # One active controller only; this check cannot lock edits from Dropbox/other machines.
        if target.read_text() != original:
            raise ValueError("External variables changed while encrypting; retry the command.")
        os.replace(pending, target)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vars-file", type=Path, default=ROOT / "external_vars.yml")
    parser.add_argument("--vault-password-file", type=Path, default=ROOT / ".ansible_pass")
    args = parser.parse_args()
    try:
        key = input("Key: ").strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError("Key must be an Ansible variable name (letters, digits and underscores; no leading digit).")
        save_variable(args.vars_file, args.vault_password_file, key)
    except (EOFError, KeyboardInterrupt):
        parser.exit(1, "\nCancelled; no files changed.\n")
    except subprocess.CalledProcessError:
        parser.exit(1, "Vault creation/editor failed; external variables unchanged.\n")
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        location = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        # Do not print YAML source snippets: they may contain plaintext secrets.
        parser.exit(1, f"Invalid YAML in {args.vars_file}{location}; check syntax and indentation. No files changed.\n")
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    print(f"Saved encrypted {key} in {args.vars_file}.")


if __name__ == "__main__":
    main()
