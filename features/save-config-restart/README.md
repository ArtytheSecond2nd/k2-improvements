# SAVE_CONFIG firmware restart protection

This feature preserves Klipper's original `SAVE_CONFIG` file update and normal
host restart, then requests exactly one `FIRMWARE_RESTART`.

A detached helper waits for the new Klippy host. If K2 motor initialization
succeeds, it continues with the firmware restart as normal. If the new host
instead enters shutdown before `motor_control.motor_ready` becomes true, or
motor initialization times out, it issues that same firmware restart as a
recovery action. This covers the stock 1.1.3.13 post-print failure without
changing the successful path used by other firmware versions and printer
states.

After the firmware restart, both Klipper `ready` and K2 `motor_ready=true` must
be confirmed. Only one firmware restart is attempted. If recovery fails, the
helper forces shutdown and requires a power cycle before homing. Diagnostic
output is written to `/tmp/k2-save-config-restart.log`.

Installer workflows use the same rule when restarting the Klippy host to load
new Python modules: motor-ready, startup-fault, and readiness-timeout outcomes
all continue to one firmware restart, followed by final readiness validation.

Creality's internal `CXSAVE_CONFIG` path is also kept synchronized with
Klipper's runtime status. An automatic save that produces identical file
content is treated as a no-op, so a firmware restart does not leave Fluidd's
Save Config button active or create another redundant backup. Successful
automatic writes clear their completed pending state without restarting.

Only the five newest primary `printer-YYYYMMDD_HHMMSS.cfg` backups are
retained. Backups with other names and backups belonging to included config
files are not removed.
