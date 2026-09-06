# SAVE_CONFIG firmware restart protection

The K2 Plus can retain an unsafe motor-controller state after Klipper's normal
host-only restart. The first subsequent `G28` may then move in the wrong
direction. This has been reproduced with both the stock PR Touch and
Cartographer installation paths.

This shared core feature preserves Klipper's normal `SAVE_CONFIG` file update
and normal restart. Before that restart begins it arms a detached helper. The
helper waits for the stock restart to be observed, waits for both Klipper and
the K2 motor controller to report ready, and then requests one protected
`FIRMWARE_RESTART` to reset the printer MCU and motor controllers.

The stock-probe and Cartographer installers both install this feature. Its
initial installation replaces Klippy's `configfile.py`, so the installer uses
a protected Klippy-code reload sequence. That installer path starts a fresh
host process, waits for both Klipper and the K2 motor controller to report
ready, and then requests one firmware restart. If motor readiness is not
confirmed, it stops without requesting that reset. Once loaded, normal
`SAVE_CONFIG` operations therefore follow the tested sequence: stock restart,
Klipper ready, motor controller ready, one `FIRMWARE_RESTART`, and final
Klipper/motor readiness verification. The detached helper logs to
`/tmp/k2-save-config-restart.log`. If any protected stage fails, it requests an
emergency shutdown so homing cannot proceed silently; fully power-cycle before
homing.
