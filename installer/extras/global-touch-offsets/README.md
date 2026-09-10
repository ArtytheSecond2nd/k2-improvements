# Global Carto Touch Z Offsets

This optional Cartographer feature adds a single `Global_Z_Offsets_Carto`
button in Fluidd's **Z Offsets** category. It discovers the saved
Cartographer Touch models instead of assuming a fixed plate list.

The dialog keeps edits locally until **Save & Restart** is pressed. Select a
Touch model, choose `0.005`, `0.010`, `0.025`, or `0.050` mm, then use the
physical-direction buttons:

- **Bed up / closer** makes the Touch offset less negative.
- **Bed down / farther** makes the Touch offset more negative.

**Cancel** discards all changes. **Save & Restart** writes only changed
`z_offset` values to their native `[cartographer touch_model ...]` sections,
runs Creality's non-restarting `CXSAVE_CONFIG`, and then runs
`FIRMWARE_RESTART`. It never invokes `SAVE_CONFIG`.

The feature carries its Fluidd dialog inside this repository as a tested
overlay for Jacob Fluidd `v1.37.4`; it does not use or update another Fluidd
repository. The installer verifies the installed version, keeps the original
web files in `fluidd.before-global-touch-offsets`, swaps in the bundled build,
and restarts nginx. Reinstalling the core Fluidd component restores Jacob's
unmodified build.

Installation also performs the required Klippy code reload and protected
firmware restart automatically. Refresh Fluidd after installation so its
service worker loads the new dialog.

The bundled `fluidd-v1.37.4.zip` is reproduced from Jacob's `v1.37.4` source
by applying the existing `features/fluidd/fluidd.patch` camera integration
first, then `fluidd-v1.37.4.patch` for this dialog.
