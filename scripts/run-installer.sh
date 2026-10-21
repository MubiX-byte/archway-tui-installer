#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if ! command -v python >/dev/null 2>&1; then
    echo 'Python 3 is required (included in the official Arch Linux ISO).' >&2
    exit 1
fi
exec python main.py "$@"
