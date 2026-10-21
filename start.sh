#!/bin/sh
# Launch the local checkout. No downloads, installs or disk operations here.
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ ! -f "$project_dir/main.py" ]; then
    printf '%s\n' 'Archway: main.py is missing. Download or clone the complete repository.' >&2
    exit 1
fi

python_bin=''
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
        python_bin=$candidate
        break
    fi
done
if [ -z "$python_bin" ]; then
    printf '%s\n' 'Archway requires Python 3.11 or newer (included in the current official Arch ISO).' >&2
    exit 1
fi

interactive=1
for argument in "$@"; do
    case "$argument" in
        --plan|--version|--help|-h) interactive=0 ;;
    esac
done
if [ "$interactive" -eq 1 ]; then
    if [ ! -t 0 ] || [ ! -t 1 ]; then
        printf '%s\n' 'Archway TUI needs an interactive terminal. For a headless preview use: sh start.sh --demo --plan' >&2
        exit 1
    fi
    case "${TERM:-}" in
        ''|dumb)
            printf '%s\n' 'Archway: terminal type is unavailable. Run from a Linux console or a configured terminal emulator.' >&2
            exit 1
            ;;
    esac
    if ! "$python_bin" -c 'import curses' 2>/dev/null; then
        printf '%s\n' 'Archway requires Python curses (included on Arch ISO). Windows demo: pip install windows-curses.' >&2
        exit 1
    fi
fi

cd -- "$project_dir"
PYTHONUNBUFFERED=1 exec "$python_bin" "$project_dir/main.py" "$@"
