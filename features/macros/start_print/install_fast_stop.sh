#!/bin/ash

set -eu

SCRIPT_DIR="$(readlink -f $(dirname "$0"))"
INSTALLER_BASE="${INSTALLER_DIR:-$(readlink -f "$SCRIPT_DIR/../../..")}"
CFG_DIR="${PRINTER_CFG_DIR:-${HOME}/printer_data/config}"
CUSTOM="$CFG_DIR/custom"
KLIPPER_ROOT="${KLIPPER_DIR:-/usr/share/klipper}"
KLIPPER_EXTRAS="$KLIPPER_ROOT/klippy/extras"
PYTHON="${K2_PYTHON:-python3}"
MINIMUM_FW=1.1.5.5

. "$INSTALLER_BASE/installer/detect/printer_fw.sh"

test -d "$CUSTOM" || mkdir -p "$CUSTOM"
[ -d "$KLIPPER_EXTRAS" ] || {
    echo "ERROR: Klipper extras directory not found: $KLIPPER_EXTRAS" >&2
    exit 1
}

firmware=$(detect_printer_fw)
if ! printer_fw_at_least "$firmware" "$MINIMUM_FW"; then
    "$PYTHON" "$INSTALLER_BASE/scripts/ensure_included.py" \
        "$CUSTOM/main.cfg" k2_start_print_fast_stop.cfg True
    rm -f "$CUSTOM/k2_start_print_fast_stop.cfg"
    rm -f "$KLIPPER_EXTRAS/k2_start_print_fast_stop.py" \
        "$KLIPPER_EXTRAS/k2_start_print_fast_stop.pyc" \
        "$KLIPPER_EXTRAS"/__pycache__/k2_start_print_fast_stop.*.pyc
    echo "I: START_PRINT Fast Stop not enabled; firmware $firmware is below $MINIMUM_FW or unknown"
    exit 0
fi

GCODE_SOURCE="$KLIPPER_ROOT/klippy/gcode.py"
if ! grep -q 'def _process_commands.*check_cancel=' "$GCODE_SOURCE" 2>/dev/null || \
   ! grep -q 'cancel_pending' "$GCODE_SOURCE" 2>/dev/null; then
    echo "ERROR: firmware $firmware does not expose the expected Creality Fast Stop API" >&2
    exit 1
fi

ln -sfn "$SCRIPT_DIR/k2_start_print_fast_stop.py" \
    "$KLIPPER_EXTRAS/k2_start_print_fast_stop.py"
ln -sfn "$SCRIPT_DIR/k2_start_print_fast_stop.cfg" \
    "$CUSTOM/k2_start_print_fast_stop.cfg"
rm -f "$KLIPPER_EXTRAS/k2_start_print_fast_stop.pyc" \
    "$KLIPPER_EXTRAS"/__pycache__/k2_start_print_fast_stop.*.pyc
"$PYTHON" "$INSTALLER_BASE/scripts/ensure_included.py" \
    "$CUSTOM/main.cfg" k2_start_print_fast_stop.cfg
touch /tmp/k2-klippy-code-restart-required
echo "I: START_PRINT Fast Stop enabled for firmware $firmware"

if [ "${1:-}" != "--no-restart" ]; then
    sh "$INSTALLER_BASE/scripts/klippy_code_restart.sh"
fi
