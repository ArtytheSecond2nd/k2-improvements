# KAMP First-Layer Footprint Scanner

This internal Klippy extension reads the selected G-code's actual first-layer
extrusion moves before printer preparation begins. The resulting conservative
rectangle includes model extrusion, brims, skirts, supports, and a prime tower,
including arc extrema. Cartographer uses it for adaptive mesh bounds and KAMP
uses it to keep the purge path outside everything printed on layer one.

Users do not install this component directly. The Cartographer and KAMP
installers both install it and perform the required protected Klippy host
reload and firmware-reset recovery.

## Behavior

- Parsing starts at the first `;LAYER_CHANGE` or `; CHANGE_LAYER` marker and
  stops at the second. Startup purge is excluded, and scan time depends on the
  first layer rather than total print duration or file size.
- Positive-extrusion `G0`/`G1`/`G2`/`G3` moves are tracked with modal absolute
  or relative XY and extrusion state. Arc cardinal extrema are included.
- The scan runs in a background worker. `PRIME_TOWER_WAIT` cooperatively waits
  for completion before `START_PRINT` moves the printer.
- Selecting another file cancels obsolete work. Results are keyed to the
  selected path, size, and modification time.
- A timeout or malformed file remains fail-open: printing continues without
  scanner geometry and reports the reason.
- An enabled prime tower combined with Creality Print's **No sparse layers
  (beta)** remains fail-closed. Such a tower can start on a later layer, which
  the first-layer scan cannot reserve and which is unsafe on the K2 Plus.
- During a pending scan, `START_PRINT` holds the sliced bed/chamber targets and
  a 140 C nozzle preheat after Creality's virtual-SD preamble resets them.

The console reports the completed scan duration, combined first-layer/object
bounds, configured margin, and final requested mesh. `klippy.log` also records
the extrusion-move count, prime-tower block count, file size, and bounds.

The public workflows and slicer requirements are covered in the
[Cartographer guide](../cartographer/README.md) and
[KAMP guide](../../installer/extras/kamp-adaptive-purge/README.md).
