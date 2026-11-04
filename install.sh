#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
dropbox_ssh_dir=${DROPBOX_SSH_DIR:-}
migrate=false
case "${1:-}" in
    '') ;;
    --migrate) migrate=true ;;
    *) printf 'Usage: %s [--migrate]\n' "$0" >&2; exit 1 ;;
esac
if (( $# > 1 )); then
    printf 'Usage: %s [--migrate]\n' "$0" >&2
    exit 1
fi
umask 077

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

sources=()
targets=()

check_file() {
    local relative=$1 shared=${2:-$1} required=${3:-false}
    local source="$dropbox_ssh_dir/$shared" target="$repo_dir/$relative"

    if [[ ! -L "$target" && "$source" -ef "$target" ]]; then
        printf 'Local and Dropbox inputs must be separate files: %s\n' "$target" >&2
        exit 1
    fi
    # Dropbox does not sync symlink contents; shared inputs must be real files.
    if [[ -L "$source" || ( -e "$source" && ! -f "$source" ) ]]; then
        printf 'Dropbox input must be a regular file: %s\n' "$source" >&2
        exit 1
    fi
    if [[ -L "$target" && "$(readlink -- "$target")" == "$source" && -f "$source" ]]; then
        : # Already linked; still include it in the manifest.
    elif [[ -e "$target" || -L "$target" ]]; then
        if [[ "$migrate" != true || -L "$target" || ! -f "$target" ]]; then
            printf 'Refusing to replace existing path: %s (use --migrate for local files)\n' "$target" >&2
            exit 1
        fi
        if [[ -f "$source" ]] && ! cmp -s -- "$source" "$target"; then
            printf 'Conflicting local and Dropbox files: %s and %s; reconcile them first.\n' "$target" "$source" >&2
            exit 1
        fi
    elif [[ ! -f "$source" ]]; then
        if [[ "$required" == true ]]; then
            printf 'Missing Dropbox file: %s\n' "$source" >&2
            exit 1
        fi
        printf 'Skipping optional input (not synced): %s\n' "$relative"
        return
    fi
    sources+=("$source")
    targets+=("$target")
}

for file in hosts external_vars.yml; do
    check_file "$file" "$file" true
done

# Controller inputs only: never sync generated profiles, keys, passwords or live state.
for file in \
    playbooks/3proxy/users.env \
    playbooks/duckdns-ui/.env \
    playbooks/firefly/.env \
    playbooks/firefly/.db.env \
    playbooks/firefly/.importer.env \
    playbooks/wake-on-lan/computers.txt; do
    check_file "$file"
done

# Cherry inputs are optional for users who only need the Ansible playbooks.
if [[ -d "$dropbox_ssh_dir/cherry-vpn" || "$migrate" == true &&
      ( -f "$repo_dir/infra/cherry-vpn/cherry-token.vault" || -f "$repo_dir/infra/cherry-vpn/terraform.tfvars" ) ]]; then
    for file in cherry-token.vault terraform.tfvars; do
        check_file "infra/cherry-vpn/$file" "cherry-vpn/$file" true
    done
else
    printf 'Skipping OpenTofu links: %s/cherry-vpn not found.\n' "$dropbox_ssh_dir"
fi

# Preflight every input before moving anything, so conflicts cannot cause a partial migration.
# No cross-controller lock; coordinate controllers and wait for Dropbox sync before switching.
for index in "${!sources[@]}"; do
    source=${sources[$index]}
    target=${targets[$index]}
    if [[ -L "$target" ]]; then
        printf 'Already linked: %s\n' "$target"
        continue
    fi
    if [[ -f "$target" ]]; then
        mkdir -p -- "$(dirname -- "$source")"
        if [[ -f "$source" ]]; then
            rm -- "$target" # Preflight verified byte-identical shared contents.
        else
            mv -- "$target" "$source"
        fi
        chmod 600 -- "$source"
    fi
    mkdir -p -- "$(dirname -- "$target")"
    ln -s -- "$source" "$target"
    printf 'Linked %s -> %s\n' "$target" "$source"
done
