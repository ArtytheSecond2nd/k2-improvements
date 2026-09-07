#!/usr/bin/env python3
"""Behavior checks for the firmware-specific case-fan compatibility flag."""

import os
import pathlib
import shlex
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = pathlib.Path(__file__).with_name("set_case_fan_compat.sh")
BASH = shutil.which("bash")
if BASH is None and os.name == "nt":
    candidate = pathlib.Path(r"C:\Program Files\Git\bin\bash.exe")
    if candidate.exists():
        BASH = str(candidate)


def shell_path(path):
    return pathlib.Path(path).resolve().as_posix()


@unittest.skipUnless(BASH, "bash is required for shell helper tests")
class CaseFanCompatibilityTests(unittest.TestCase):
    def run_helper(self, config, firmware):
        command = "sh {} {} {}".format(
            shlex.quote(shell_path(SCRIPT)),
            shlex.quote(shell_path(config)),
            shlex.quote(firmware),
        )
        result = subprocess.run(
            [BASH, "-lc", command],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_only_confirmed_affected_firmware_is_enabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = pathlib.Path(temp_dir) / "overrides.cfg"
            config.write_text(
                "[gcode_macro _START_PRINT_VARS]\n"
                "variable_release_stock_case_fan: 0\n"
                "gcode:\n",
                encoding="utf-8",
            )

            self.run_helper(config, "1.1.3.13")
            self.assertIn(
                "variable_release_stock_case_fan: 1", config.read_text()
            )

            self.run_helper(config, "1.1.5.5")
            self.assertIn(
                "variable_release_stock_case_fan: 0", config.read_text()
            )

    def test_unknown_firmware_defaults_off_and_missing_flag_is_added(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = pathlib.Path(temp_dir) / "overrides.cfg"
            config.write_text(
                "[gcode_macro _START_PRINT_VARS]\n"
                "variable_offset_PLA: 0\n"
                "gcode:\n",
                encoding="utf-8",
            )

            self.run_helper(config, "unknown")
            updated = config.read_text(encoding="utf-8")
            self.assertIn("variable_release_stock_case_fan: 0", updated)
            self.assertIn("variable_offset_PLA: 0", updated)


if __name__ == "__main__":
    unittest.main()
