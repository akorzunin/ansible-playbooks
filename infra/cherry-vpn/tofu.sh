#!/usr/bin/env bash
# Decrypt only into the child environment; never source secrets as shell code.
set +x
set -euo pipefail
umask 077
cd -- "$(dirname -- "$0")"

vault_file="$PWD/cherry-token.vault"
password_file="$PWD/../../.ansible_pass"
if [[ -z "${CHERRY_API_KEY:-}" && -f "$vault_file" ]]; then
  CHERRY_API_KEY="$(ansible-vault view --vault-password-file "$password_file" "$vault_file")"
  if [[ -z "$CHERRY_API_KEY" || "$CHERRY_API_KEY" == *[[:space:]]* ]]; then
    printf 'Vault must contain only a single nonempty API token, not YAML.\n' >&2
    exit 1
  fi
  export CHERRY_API_KEY
fi

if [[ -x .tools/tofu ]]; then
  exec .tools/tofu "$@"
fi
exec tofu "$@"
