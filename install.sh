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

# Absolute sources keep links valid when DROPBOX_SSH_DIR is relative.
dropbox_ssh_dir=$(cd -- "$dropbox_ssh_dir" && pwd)

link_file() {
    local source=$1 target=$2

    if [[ ! -f "$source" ]]; then
        printf 'Missing Dropbox file: %s\n' "$source" >&2
        exit 1
    fi

    if [[ -e "$target" || -L "$target" ]]; then
        if [[ -L "$target" && "$(readlink -- "$target")" == "$source" ]]; then
            printf 'Already linked: %s\n' "$target"
            return
        fi

        printf 'Refusing to replace existing path: %s\n' "$target" >&2
        exit 1
    fi

    ln -s -- "$source" "$target"
    printf 'Linked %s -> %s\n' "$target" "$source"
}

for file in hosts external_vars.yml; do
    link_file "$dropbox_ssh_dir/$file" "$repo_dir/$file"
done

# Cherry inputs are optional for users who only need the Ansible playbooks.
if [[ -d "$dropbox_ssh_dir/cherry-vpn" ]]; then
    for file in cherry-token.vault terraform.tfvars; do
        link_file "$dropbox_ssh_dir/cherry-vpn/$file" "$repo_dir/infra/cherry-vpn/$file"
    done
else
    printf 'Skipping OpenTofu links: %s/cherry-vpn not found.\n' "$dropbox_ssh_dir"
fi
