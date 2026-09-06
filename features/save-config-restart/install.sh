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

echo "I: installed K2 Plus protected post-SAVE_CONFIG restart sequence"

if [ "${1:-}" != "--no-restart" ]; then
    sh ${SCRIPT_DIR}/../../scripts/klippy_code_restart.sh
fi
