# Axis Twist Compensation

Compensates for Z-height drift across the X or Y axis. It can improve first layers,
but it may also hide a mechanical bed or gantry problem. Check the printer
mechanically before enabling this optional feature.

Calibration coordinates describe physical bed locations. Before moving, the
feature reads the active probe's effective X/Y offsets and the toolhead's
actual axis limits, then reduces the requested area when necessary. A stock
probe with zero offsets keeps the configured area. Front- or rear-mounted
Cartographer probes, including custom offsets, automatically shift the safe
calibration boundary in the corresponding direction.

## Calibration

The installer replaces loaded Klippy Python modules, then performs the
protected Klippy host reload, firmware-reset recovery, and K2 motor
initialization wait. When it completes successfully, run:

```gcode
G28
Z_TILT_ADJUST
AXIS_TWIST_COMPENSATION_CALIBRATE AUTO=TRUE SAMPLE_COUNT=10
SAVE_CONFIG
```

`SAMPLE_COUNT` applies to each axis in AUTO mode, so `SAMPLE_COUNT=10`
collects a 10 by 10 grid of 100 measurements. The console reports the active
probe offsets and calculated safe bed area before motion begins. Review that
line and the resulting correction arrays before running `SAVE_CONFIG`.
