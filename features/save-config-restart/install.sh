#!/bin/ash
set -e

SCRIPT_DIR=$(readlink -f $(dirname ${0}))
TARGET=~/klipper/klippy/configfile.py
HELPER=~/klipper/klippy/k2_save_config_restart.sh

# Remove cached bytecode so the next Klipper start must load the managed file.
rm -f ~/klipper/klippy/configfile.pyc \
    ~/klipper/klippy/__pycache__/configfile.*.pyc
ln -sfn ${SCRIPT_DIR}/configfile.py ${TARGET}
ln -sfn ${SCRIPT_DIR}/k2_save_config_restart.sh ${HELPER}
chmod +x ${SCRIPT_DIR}/k2_save_config_restart.sh

# Remove the historical backlog on refresh. Runtime SAVE_CONFIG and
# CXSAVE_CONFIG calls enforce the same five-backup limit after each write.
CFG_DIR="${PRINTER_CFG_DIR:-/mnt/UDISK/printer_data/config}"
find "$CFG_DIR" -maxdepth 1 -type f \
    -name 'printer-????????_??????.cfg' 2>/dev/null |
    grep -E '/printer-[0-9]{8}_[0-9]{6}\.cfg$' |
    sort -r |
    awk 'NR > 5' |
    while IFS= read -r backup; do
        rm -f "$backup"
        echo "I: removed old printer config backup $backup"
    done

echo "I: installed K2 Plus protected post-SAVE_CONFIG restart sequence"

if [ "${1:-}" != "--no-restart" ]; then
    sh ${SCRIPT_DIR}/../../scripts/klippy_code_restart.sh
fi
