# Stock SAVE_CONFIG restart behavior

This shared core feature keeps Klipper's original `SAVE_CONFIG` behavior: it
writes the configuration and requests a normal Klippy host restart.

There is no detached wrapper, follow-up `FIRMWARE_RESTART`, or automatic
recovery attempt. If the K2 motor controller does not initialize after
`SAVE_CONFIG`, fully power-cycle the printer before homing.
