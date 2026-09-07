#!/bin/sh
# Maintain the firmware-specific case-fan compatibility flag in overrides.cfg.

set -eu

CFG="$1"
PRINTER_FW="${2:-unknown}"
VARIABLE=variable_release_stock_case_fan

[ -f "$CFG" ] || {
    echo "ERROR: overrides config not found: $CFG"
    exit 1
}

# Add firmware versions here only after the forced pre-print case-fan behavior
# has been reproduced on that version. Unknown and unlisted versions remain off.
case "$PRINTER_FW" in
    1.1.3.13) DESIRED=1 ;;
    *) DESIRED=0 ;;
esac

CURRENT=$(awk -v key="$VARIABLE" '
BEGIN { in_vars=0 }
/^\[gcode_macro _START_PRINT_VARS\]$/ { in_vars=1; next }
in_vars && /^\[/ { in_vars=0 }
in_vars && $0 ~ "^[[:space:]]*" key "[[:space:]]*:" {
    sub(/^[^:]*:[[:space:]]*/, "")
    sub(/[[:space:]]*#.*/, "")
    print
    exit
}
' "$CFG")

if [ "$CURRENT" = "$DESIRED" ]; then
    echo "I: firmware $PRINTER_FW case-fan compatibility already set to $DESIRED"
    exit 0
fi

BACKUP="${CFG}.before-case-fan-compat-$(date +%s)"
cp -p "$CFG" "$BACKUP"

if ! awk -v key="$VARIABLE" -v desired="$DESIRED" '
BEGIN { in_vars=0; written=0 }
/^\[gcode_macro _START_PRINT_VARS\]$/ { in_vars=1 }
in_vars && $0 ~ "^[[:space:]]*" key "[[:space:]]*:" {
    print key ": " desired " # installer-managed firmware compatibility flag"
    written=1
    next
}
in_vars && /^gcode:[[:space:]]*$/ && !written {
    print key ": " desired " # installer-managed firmware compatibility flag"
    written=1
}
{ print }
END { if (!written) exit 1 }
' "$CFG" > "${CFG}.new"; then
    rm -f "${CFG}.new"
    echo "ERROR: could not set $VARIABLE in $CFG"
    echo "       backup retained at $BACKUP"
    exit 1
fi

mv "${CFG}.new" "$CFG"
echo "I: firmware $PRINTER_FW case-fan compatibility set to $DESIRED"
echo "I: overrides backup at $BACKUP"
