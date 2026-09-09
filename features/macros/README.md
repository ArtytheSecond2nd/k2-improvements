# K2 Plus Macro Bundle

Installs the four macro components used by both guided setup paths:

- [`START_PRINT`](./start_print/README.md)
- [`M191`](./m191/README.md)
- [temperature-aware bed mesh macros](./bed_mesh/README.md)
- `custom/overrides.cfg`

The overrides file is created only when missing. Re-running the installer
preserves existing mount selections and user changes. New files seed the PLA,
PETG, ABS, ASA, and default offsets at `0`, along with a zero-minute heat soak.
Obsolete installer-managed entries are removed during updates; firmware
compatibility state is kept in managed files rather than exposed as a user
setting.

The separate `variable_bed_mesh_soak` setting defaults to five minutes and is
used only when the stock-probe workflow must create a missing saved mesh. Users
who heat soak before sending a print can set it to `0`.

The same overrides template serves both setup paths. When Cartographer is
present, its installer adds one active `[cartographer touch]` section with the
stock `max_noisy_samples: 2` value. That Cartographer-only section is absent
from a stock PR Touch installation, and existing user-selected values are
preserved on reinstall.

On firmware `1.1.3.13`, installation also enables a compatibility definition
for the missing `SET_TEMPERATURE_FAN_SWITCH` command still called by Creality's
stock macros. It is a no-op because those macros already set the chamber-fan
target and pin directly. The definition is disabled on all other firmware.

Each macro is included from `custom/main.cfg`. The combined installer performs
one firmware restart after all four components are installed and waits for K2
motor initialization before returning.
