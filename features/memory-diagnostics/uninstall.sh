#!/bin/sh
set -eu

INSTALLER_BASE="${INSTALLER_DIR:-/mnt/UDISK/k2-improvements}"
CFG_DIR="${PRINTER_CFG_DIR:-/mnt/UDISK/printer_data/config}"
CUSTOM="$CFG_DIR/custom"
KLIPPER_ROOT="${KLIPPER_DIR:-${HOME}/klipper}"
KLIPPER_EXTRAS="$KLIPPER_ROOT/klippy/extras"
PYTHON="${K2_PYTHON:-python3}"

"$PYTHON" "$INSTALLER_BASE/scripts/ensure_included.py" \
    "$CUSTOM/main.cfg" memory_diagnostics.cfg true
rm -f "$CUSTOM/memory_diagnostics.cfg" \
    "$KLIPPER_EXTRAS/memory_diagnostics.py" \
    "$KLIPPER_EXTRAS/memory_diagnostics.pyc" \
    "$KLIPPER_EXTRAS/__pycache__/memory_diagnostics."*.pyc

echo "I: removed memory diagnostics; existing bounded logs were retained"
sh "$INSTALLER_BASE/scripts/klippy_code_restart.sh"
