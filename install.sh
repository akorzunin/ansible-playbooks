#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
dropbox_ssh_dir=${DROPBOX_SSH_DIR:-}

if [[ -z "$dropbox_ssh_dir" ]]; then
    for candidate in "$HOME/Dropbox/ssh" "$HOME/storage/shared/Dropbox/ssh"; do
        if [[ -d "$candidate" ]]; then
            dropbox_ssh_dir=$candidate
            break
        fi
    done
fi

if [[ -z "$dropbox_ssh_dir" ]]; then
    printf 'Dropbox ssh directory not found. Set DROPBOX_SSH_DIR to its path.\n' >&2
    exit 1
fi

for file in hosts external_vars.yml; do
    source="$dropbox_ssh_dir/$file"
    target="$repo_dir/$file"

    if [[ ! -f "$source" ]]; then
        printf 'Missing Dropbox file: %s\n' "$source" >&2
        exit 1
    fi

    if [[ -e "$target" || -L "$target" ]]; then
        if [[ -L "$target" && "$(readlink -- "$target")" == "$source" ]]; then
            printf 'Already linked: %s\n' "$target"
            continue
        fi

        printf 'Refusing to replace existing path: %s\n' "$target" >&2
        exit 1
    fi

    ln -s -- "$source" "$target"
    printf 'Linked %s -> %s\n' "$target" "$source"
done
