#!/usr/bin/env python3
"""Release prtouch_v3's axis-twist object name for the full ATC module."""

import pathlib
import shutil
import sys


DEFAULT_TARGET = pathlib.Path(
    "/usr/share/klipper/klippy/extras/prtouch_v3.py"
)
REGISTRATION = (
    "    config.get_printer().add_object"
    "('axis_twist_compensation', prtouch)"
)
PATCHED_REGISTRATION = (
    "    # K2-Improvements supplies the full axis-twist object when this "
    "optional feature is installed."
)


def patch_file(target):
    target = pathlib.Path(target)
    source = target.read_text(encoding="utf-8")

    if PATCHED_REGISTRATION in source:
        return False
    if source.count(REGISTRATION) != 1:
        raise RuntimeError(
            "expected exactly one prtouch_v3 axis-twist registration in %s"
            % (target,)
        )

    backup = target.with_name(target.name + ".k2-axis-twist.bak")
    if not backup.exists():
        shutil.copy2(str(target), str(backup))

    target.write_text(
        source.replace(REGISTRATION, PATCHED_REGISTRATION),
        encoding="utf-8",
    )
    return True


def main():
    target = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_TARGET
    changed = patch_file(target)
    state = "patched" if changed else "already patched"
    print("prtouch_v3 axis-twist registration: %s" % (state,))


if __name__ == "__main__":
    main()
