#!/bin/sh
# Compatibility entrypoint; keep all launcher checks in the root start.sh.
set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec sh "$script_dir/../start.sh" "$@"
