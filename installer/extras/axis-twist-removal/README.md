# Remove legacy Axis Twist

Axis Twist Compensation (ATC) is retired from this installer. Installing the old
extra replaced Creality's stock `probe.py` even when ATC was never calibrated.
That replacement omitted stock per-probe temperature correction, the later
probe-depth limit, and the stock firmware's cancellation check. This does not
mean ATC necessarily caused a particular first-layer problem: the recent saved-
mesh and regenerated-mesh PETG tests remained good without changing offsets.

## Remove an existing installation

Use **Optional extras → Remove legacy Axis Twist** only if you choose to remove
ATC. Repository updates and **Apply all recommended updates** do not uninstall
ATC or require its removal. Existing runtime source files remain at their old
paths so installed links continue to work after a pull and restart. The install
option and installer script are retired; the retained files are compatibility
support for existing installations, not an invitation to install ATC.
The Extras menu hides the action when no legacy ATC artifacts are detected and
rechecks detection when selected, so entering an old option number or using a
stale menu does not launch removal. Other option numbers remain unchanged.
After successful removal the Extras option disappears automatically. The
restoration migration ID records a successful manual uninstall only; it never
adds removal to the recommended-update plan, even with an old update snapshot.

The printer must be idle and Klipper ready. Save pending meshes/calibration
with `SAVE_CONFIG` first and wait for its protected restart to finish. The
uninstaller refuses printing, paused jobs, active operations, disconnected
Klipper, and unsaved calibration; it never sends `SAVE_CONFIG` or motion.

For a read-only preflight in the printer SSH terminal:

```sh
sh /mnt/UDISK/root/k2-improvements/installer/extras/axis-twist-removal/uninstall.sh --check-only
```

The normal terminal entry point is the same command without `--check-only`.
Prefer the menu: it displays the removal warning and asks for confirmation.

## Restoration and safety

- The full MD5 **and SHA-256** of `prtouch_v3_wrapper.cpython-39.so` select one of
  three OTA-extracted stock helpers. The wrapper itself is never modified.
- Unknown/missing wrappers or unexpected probe edits stop before any changes.
  For an unknown wrapper, restore/reflash the matching stock firmware; do not
  guess a helper from the displayed firmware version.
- A verified `prtouch_v3.py.k2-axis-twist.bak` is preferred. Without it, only the
  recognized registration rename (or the old registration-removal patch) is
  reversed. Unrelated modifications or an invalid backup are refused.
- Exact ATC includes, the ATC config/module links, and active or `SAVE_CONFIG`
  `[axis_twist_compensation]` sections are removed. Other sections, saved meshes,
  global-offset JSON, material offsets, and unrelated files are retained.
- Cartographer installs retain `self.use_offsets = True` in the restored stock
  helper, preserving the probe XY offset handling used by `Z_TILT_ADJUST`.
- Every changed/removed file and link is recorded under
  `printer_data/config/atc-removal-backups/<timestamp>-<unique>/`, including a
  manifest with original paths, link targets, modes, and available file contents.
  A deleted checkout may leave dangling ATC links; their targets are recorded
  even if their original content is no longer available.
- Sources are verified before mutation, writes are atomic, and an edit failure
  attempts rollback. Keep the backup and do not home if rollback/restart fails.
- After successful file restoration, the existing protected Klippy host reload,
  firmware reset, and K2 motor-readiness sequence runs. Plain `RESTART` is not a
  substitute for reloading imported Python code.

Re-mesh and recheck global/material Z offsets afterward, using the same reference
filament, process, plate, and temperatures. Existing meshes are deliberately not
deleted automatically; preserve them if doing a controlled comparison.

The removed calibration values are recoverable from the backups but are not
loaded by stock probing. A Cartographer-only calibration holder could be added
separately later; this removal does not install one.

## Shipped stock source provenance

Stock sources retain their upstream GPLv3 copyright/license headers. Extracted
from the OTA `cpio` archive's SquashFS `rootfs`, path
`usr/share/klipper/klippy/extras/`. The Python fixtures use LF line endings;
`prtouch_v3.py` in the OTA uses CRLF, normalized only for integrity comparison.

| Wrapper MD5 (full) | Stock helper | Stock probe SHA-256 |
|---|---|---|
| `0dfd58494d4a580f07e0e0b349ee4531` | 1.1.3.13 | `27415070c0beff9e38aa53491d1e4f2f4f3a2f20d498e59e641de06db199cc1b` |
| `c6878561b7b13c2023df7faebf90934b` | 1.1.5.2 | `46ffcf8f330fd0ce1253aaca0d8d77c1f88207008f9ee436345e7dc9c2b49674` |
| `d020e2a1db363c46f4ace6a9aa8c82b5` | 1.1.5.5 (also matching 1.1.6.x / 1.1.7.0 wrappers) | `d6917fc49e31088096151291d89c0f69292362bbc8d36ac16ef8f767d1cad0a4` |

- 1.1.3.13: re-extracted from the retained OTA `rootfs`; [official OTA download](https://file2-cdn.creality.com/file/2af16919096368092e7fab5da7436c70/CR0CN240110C10_ota_img_V1.1.3.13.img).
- 1.1.5.2: [official OTA download](https://file2-cdn.creality.com/file/8e0f4fe81154a7d84cfd2cc29e13817f/CR0CN240110C10_R_202603311917_ota_img_V1.1.5.2.img).
  Image MD5 `8e0f4fe81154a7d84cfd2cc29e13817f`, SHA-256
  `8bb24148e98d7d490e025e9e81702ac59e17559d0bf6e9011c1c1e1ab6425615`.
- 1.1.5.5: re-extracted and cross-checked against the [official K2 Plus OTA download](https://file2-cdn.creality.com/file/061e5074c360584d65ff4ae3aba9c028/CR0CN240110C10_R_202605081127_ota_img_V1.1.5.5.img),
  image SHA-256 `d83e738cca980202391fc60ad039f850368e98a0836679111145e6e28ae1698d`.

Full wrapper SHA-256 identities are pinned alongside the MD5 identities in
`remove_axis_twist.py`. No binaries or OTA images are shipped or downloaded by
the runtime uninstaller.
