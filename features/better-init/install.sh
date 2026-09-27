#!/bin/ash
set -e

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")

# these are replacing the default init scripts and MUST be copied
cp -f ${SCRIPT_DIR}/klipper_mcu.init /etc/init.d/klipper_mcu
/etc/init.d/klipper_mcu restart
cp -f ${SCRIPT_DIR}/klipper.init /etc/init.d/klipper
cp -f ${SCRIPT_DIR}/webrtc.init /etc/init.d/webrtc
/etc/init.d/webrtc restart

# need to link wrapper scripts in place
# linking so they get updates
test -d /mnt/UDISK/bin || mkdir -p /mnt/UDISK/bin

ln -sf ${SCRIPT_DIR}/bin/sudo /mnt/UDISK/bin/
ln -sf ${SCRIPT_DIR}/bin/supervisorctl /mnt/UDISK/bin/
ln -sf ${SCRIPT_DIR}/bin/systemctl /mnt/UDISK/bin/

# update the path
echo 'export PATH=/mnt/UDISK/bin:$PATH' > /etc/profile.d/better-init.sh

# Moonraker builds its recurring provider command from the first successful
# service discovery. Reload it after replacing supervisorctl so an older empty
# or stale command cannot survive an Improved Init refresh.
if [ -x /etc/init.d/moonraker ]; then
    /etc/init.d/moonraker restart
fi

if [ "${K2_DEFER_FIRMWARE_RESTART:-0}" != 1 ]; then
    sh "${SCRIPT_DIR}/../../scripts/klippy_code_restart.sh"
fi
