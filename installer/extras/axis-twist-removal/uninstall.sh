#!/bin/sh
set -eu

SCRIPT_DIR="$(readlink -f "$(dirname "$0")")"
REPO_ROOT="$(readlink -f "$SCRIPT_DIR/../../..")"
INSTALLER_BASE="${INSTALLER_DIR:-$REPO_ROOT}"
PYTHON="${K2_PYTHON:-python3}"
case "${1:-}" in
    --check-only)
        exec "$PYTHON" "$SCRIPT_DIR/remove_axis_twist.py" --check-only
        ;;
    '') ;;
    *) echo 'E: usage: uninstall.sh [--check-only]' >&2; exit 1 ;;
esac

result=0
"$PYTHON" "$SCRIPT_DIR/remove_axis_twist.py" --apply || result=$?
case "$result" in
    0)
        # A full host reload is required after replacing imported Python files.
        sh "$INSTALLER_BASE/scripts/klippy_code_restart.sh"
        ;;
    3) exit 0 ;;
    *) exit "$result" ;;
esac
