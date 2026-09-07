#!/bin/ash

# This process is detached before Klipper performs its normal SAVE_CONFIG host
# restart.  It waits until that replacement host either finishes K2 motor
# discovery or enters the known startup fault, then requests one firmware
# restart in both cases and verifies the recovered motor state.

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
    echo "E: firmware recovery failed; power-cycle before any homing test"
    exit 1
}

echo ""
echo "I: protected SAVE_CONFIG restart armed at $(date)"
touch "$ARMED"

# Reject the old ready session.  The helper must first observe the disconnect
# caused by the stock SAVE_CONFIG host restart.
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

# A good host restart and the known failed host restart both require the same
# final firmware restart.  Waiting here prevents us from interrupting normal
# motor discovery, while recognizing shutdown avoids the former dead end.
COUNT=0
OUTCOME=timeout
while [ "$COUNT" -lt "$TIMEOUT" ]; do
    INFO=$($CURL -fsS --max-time 2 "$API_URL/printer/info" 2>/dev/null || true)
    if printf '%s' "$INFO" | \
        grep -qE '"state"[[:space:]]*:[[:space:]]*"ready"'; then
        MOTOR_INFO=$($CURL -fsS --max-time 2 \
            "$API_URL/printer/objects/query?motor_control=motor_ready" \
            2>/dev/null || true)
        if printf '%s' "$MOTOR_INFO" | \
            grep -qE '"motor_ready"[[:space:]]*:[[:space:]]*true'; then
            OUTCOME=motors-ready
            break
        fi
    elif printf '%s' "$INFO" | \
        grep -qE '"state"[[:space:]]*:[[:space:]]*"(error|shutdown)"'; then
        OUTCOME=startup-fault
        break
    fi
    COUNT=$((COUNT + 1))
    sleep 1
done

case "$OUTCOME" in
    motors-ready)
        echo "I: fresh Klippy host and K2 motors are ready; continuing with one firmware restart"
        ;;
    startup-fault)
        echo "W: fresh Klippy host entered shutdown before K2 motors became ready"
        echo "I: continuing with one firmware restart to recover the motor controller"
        ;;
    *)
        echo "W: fresh Klippy host did not finish K2 motor initialization within ${TIMEOUT} seconds"
        echo "I: continuing with one firmware restart to recover the motor controller"
        ;;
esac

if ! K2_DEFER_FIRMWARE_RESTART=0 K2_FIRMWARE_RESTART_ATTEMPTS=1 \
    K2_WAIT_FOR_KLIPPY_STARTUP=0 K2_MOTOR_READY_TIMEOUT="$TIMEOUT" \
    sh "$SCRIPT_DIR/../../scripts/firmware_restart.sh"; then
    fail_closed
fi

echo "I: protected SAVE_CONFIG restart completed successfully"
