#!/bin/ash

# This process is detached by configfile.py before Klipper performs its normal
# SAVE_CONFIG restart.  It observes that transition, waits for the restarted
# Klipper session and K2 motor controller, and only then requests the same
# guarded firmware restart used by the installer.

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
API_URL="${MOONRAKER_URL:-http://127.0.0.1:7125}"
TIMEOUT="${K2_SAVE_CONFIG_TIMEOUT:-60}"
ARMED=/tmp/k2-save-config-restart.armed
LOCKDIR=/tmp/k2-save-config-restart.lock

if [ -n "${K2_CURL:-}" ]; then
    CURL=$K2_CURL
elif [ -x /opt/bin/curl ]; then
    CURL=/opt/bin/curl
elif command -v curl >/dev/null 2>&1; then
    CURL=$(command -v curl)
else
    echo "E: curl is required for protected SAVE_CONFIG recovery"
    exit 1
fi

case "$TIMEOUT" in
    ''|*[!0-9]*|0)
        echo "E: K2_SAVE_CONFIG_TIMEOUT must be a positive integer"
        exit 1
        ;;
esac

if ! mkdir "$LOCKDIR" 2>/dev/null; then
    echo "E: another protected SAVE_CONFIG restart is already active"
    exit 1
fi

cleanup() {
    rm -f "$ARMED"
    rmdir "$LOCKDIR" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

fail_closed() {
    echo "E: protected SAVE_CONFIG restart failed; forcing Klipper shutdown"
    "$CURL" -fsS --max-time 5 -X POST \
        "$API_URL/printer/emergency_stop" >/dev/null 2>&1 || true
    echo "E: power-cycle the printer before any homing test"
    exit 1
}

echo ""
echo "I: protected SAVE_CONFIG restart armed at $(date)"
touch "$ARMED"

# Do not accept the old ready session.  First observe the disconnect or a
# non-ready state caused by Klipper's stock SAVE_CONFIG restart.
COUNT=0
TRANSITION=0
while [ "$COUNT" -lt "$TIMEOUT" ]; do
    INFO=$($CURL -fsS --max-time 2 "$API_URL/printer/info" 2>/dev/null || true)
    if ! printf '%s' "$INFO" | \
        grep -qE '"state"[[:space:]]*:[[:space:]]*"ready"'; then
        TRANSITION=1
        break
    fi
    COUNT=$((COUNT + 1))
    sleep 1
done

if [ "$TRANSITION" -ne 1 ]; then
    echo "E: stock SAVE_CONFIG restart transition was not observed"
    fail_closed
fi

echo "I: stock SAVE_CONFIG Klipper restart observed"
if ! K2_DEFER_FIRMWARE_RESTART=0 K2_FIRMWARE_RESTART_ATTEMPTS=1 \
    K2_WAIT_FOR_KLIPPY_STARTUP=1 K2_MOTOR_READY_TIMEOUT="$TIMEOUT" \
    sh "$SCRIPT_DIR/../../scripts/firmware_restart.sh"; then
    fail_closed
fi

echo "I: protected SAVE_CONFIG restart completed successfully"
