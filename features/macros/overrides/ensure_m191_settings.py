#!/usr/bin/env python3
"""Add missing M191 defaults to a preserved custom overrides file."""

import os
import re
import shutil
import stat
import sys
import tempfile
import time


SECTION_NAME = "gcode_macro _M191_VARS"
SECTION_RE = re.compile(r"^[ \t]*\[([^]]+)\][ \t]*(?:#.*)?(?:\r?\n)?$")
VARIABLE_RE = re.compile(r"^[ \t]*variable_([A-Za-z0-9_]+)[ \t]*:", re.I)
LEGACY_CIRCULATION_DEFAULT_RE = re.compile(
    r"^([ \t]*variable_circulation_fan_speed[ \t]*:[ \t]*)"
    r"25(?:\.0+)?([ \t]*(?:\r?\n)?)$",
    re.I,
)
DEFAULTS = (
    ("bed_assist_enabled", "1"),
    ("bed_assist_trigger_delta", "3.0"),
    ("bed_assist_bed_target", "105.0"),
    ("bed_assist_degrees_above_commanded", "0.0"),
    ("bed_assist_z_height", "195.0"),
    ("circulation_fan_speed", "15.0"),
    ("circulation_fan_high_speed", "100.0"),
    ("circulation_fan_low_seconds", "45.0"),
    ("circulation_fan_high_seconds", "20.0"),
    ("bed_restore_z_height", "30.0"),
    ("bed_restore_side_fan_speed", "100.0"),
    ("chamber_fan_margin", "2.0"),
    ("bed_restore_tolerance", "5.0"),
    ("chamber_wait_max_delta", "5.0"),
)


def update(contents):
    """Return overrides text with every M191 setting present."""
    newline = "\r\n" if "\r\n" in contents else "\n"
    lines = contents.splitlines(keepends=True)
    section_indexes = []
    for index, line in enumerate(lines):
        match = SECTION_RE.match(line)
        if match and match.group(1).strip().casefold() == SECTION_NAME.casefold():
            section_indexes.append(index)

    if len(section_indexes) > 1:
        raise ValueError("multiple [%s] sections were found" % SECTION_NAME)

    if not section_indexes:
        if contents and not contents.endswith(("\n", "\r")):
            contents += newline
        if contents and not contents.endswith(newline * 2):
            contents += newline
        settings = "".join(
            "variable_%s: %s%s" % (name, value, newline)
            for name, value in DEFAULTS
        )
        return (
            contents
            + "[%s]%s" % (SECTION_NAME, newline)
            + settings
            + "gcode:%s" % newline
        )

    start = section_indexes[0]
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if SECTION_RE.match(lines[index]):
            end = index
            break

    existing = set()
    gcode_index = None
    for index in range(start + 1, end):
        legacy_default = LEGACY_CIRCULATION_DEFAULT_RE.match(lines[index])
        if legacy_default:
            lines[index] = legacy_default.group(1) + "15.0" + legacy_default.group(2)
        body = lines[index].strip()
        match = VARIABLE_RE.match(lines[index])
        if match:
            existing.add(match.group(1).casefold())
        if body.casefold() == "gcode:":
            gcode_index = index
            break

    if gcode_index is None:
        raise ValueError("[%s] has no gcode: line" % SECTION_NAME)

    missing = [item for item in DEFAULTS if item[0].casefold() not in existing]
    if not missing:
        return "".join(lines)

    additions = [
        "variable_%s: %s%s" % (name, value, newline)
        for name, value in missing
    ]
    lines[gcode_index:gcode_index] = additions
    return "".join(lines)


def write_atomic(path, contents):
    mode = stat.S_IMODE(os.stat(path).st_mode)
    directory = os.path.dirname(path) or "."
    descriptor, temporary = tempfile.mkstemp(
        prefix=".m191-settings-", dir=directory, text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as output:
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    path = os.path.expanduser(
        sys.argv[1]
        if len(sys.argv) > 1
        else "~/printer_data/config/custom/overrides.cfg"
    )
    if not os.path.isfile(path):
        sys.stderr.write("ERROR: overrides config not found: %s\n" % path)
        return 1

    with open(path, "r", encoding="utf-8", newline="") as source:
        original = source.read()
    try:
        updated = update(original)
    except ValueError as exc:
        sys.stderr.write("ERROR: could not add M191 settings: %s\n" % exc)
        return 1

    if updated == original:
        print("I: preserving existing M191 settings in %s" % path)
        return 0

    backup = "%s.before-m191-settings-%d" % (path, int(time.time()))
    shutil.copy2(path, backup)
    write_atomic(path, updated)
    print("I: added missing M191 settings to %s" % path)
    print("I: overrides backup at %s" % backup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
