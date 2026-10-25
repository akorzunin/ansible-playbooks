#!/usr/bin/env bash
# Never trace decrypted environment values, even when invoked with bash -x.
set +x
set -euo pipefail
umask 077
cd -- "$(dirname -- "$0")"
exec python3 tofu.py "$@"
