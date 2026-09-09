#!/usr/bin/env python3
"""Remove obsolete installer-managed entries from the user overrides file."""

import os
import re
import stat
import sys
import tempfile


START_VARS_RE = re.compile(
    r"^\s*\[gcode_macro\s+_START_PRINT_VARS\]\s*$", re.I
)
STALE_VARIABLE_RE = re.compile(
    r"^\s*variable_(?:offset_PROBE|release_stock_case_fan)\s*:", re.I
)
LEGACY_CARTO_PLACEHOLDER_RE = re.compile(
    r"(?m)^[ \t]*# Cartographer-only default\. The installer activates this section in the\r?\n"
    r"^[ \t]*# installed overrides\.cfg when Cartographer is present\.\r?\n"
    r"^[ \t]*# \[cartographer touch\]\r?\n"
    r"^[ \t]*# max_noisy_samples: 2\r?\n?"
)


def clean(contents):
    contents, placeholder_count = LEGACY_CARTO_PLACEHOLDER_RE.subn("", contents)
    lines = contents.splitlines(keepends=True)
    in_start_vars = False
    removed_variables = []
    output = []

    for line in lines:
        body = line.rstrip("\r\n")
        if body.lstrip().startswith("["):
            in_start_vars = bool(START_VARS_RE.match(body))

        if in_start_vars and STALE_VARIABLE_RE.match(body):
            name = body.split(":", 1)[0].strip()
            removed_variables.append(name)
            continue

        output.append(line)

    return "".join(output), removed_variables, bool(placeholder_count)


def main():
    path = os.path.expanduser(
        sys.argv[1]
        if len(sys.argv) > 1
        else "~/printer_data/config/custom/overrides.cfg"
    )
    if not os.path.isfile(path):
        return 0

    with open(path, "r", encoding="utf-8", newline="") as handle:
        original = handle.read()

    updated, removed_variables, removed_placeholder = clean(original)
    if updated == original:
        return 0

    mode = stat.S_IMODE(os.stat(path).st_mode)
    directory = os.path.dirname(path) or "."
    fd, temporary = tempfile.mkstemp(
        prefix=".overrides-cleanup-", dir=directory, text=True
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(updated)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

    removed = list(removed_variables)
    if removed_placeholder:
        removed.append("commented Cartographer Touch placeholder")
    print("I: removed obsolete managed overrides: {}".format(", ".join(removed)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
