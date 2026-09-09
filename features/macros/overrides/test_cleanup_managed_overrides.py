#!/usr/bin/env python3
"""Behavior checks for obsolete managed override cleanup."""

import importlib.util
import pathlib
import tempfile
import unittest
from unittest import mock


MODULE_PATH = pathlib.Path(__file__).with_name("cleanup_managed_overrides.py")
SPEC = importlib.util.spec_from_file_location("cleanup_managed_overrides", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ManagedOverridesCleanupTests(unittest.TestCase):
    def test_removes_only_stale_start_print_entries_and_placeholder(self):
        contents = (
            "[gcode_macro _START_PRINT_VARS]\n"
            "variable_offset_PLA: 0.03\n"
            "variable_offset_PROBE: 1\n"
            "variable_release_stock_case_fan: 1\n"
            "variable_carto_touch_calibrate_start: 2000\n"
            "gcode:\n\n"
            "# Cartographer-only default. The installer activates this section in the\n"
            "# installed overrides.cfg when Cartographer is present.\n"
            "# [cartographer touch]\n"
            "# max_noisy_samples: 2\n\n"
            "[cartographer touch]\n"
            "max_noisy_samples: 4\n"
        )

        updated, removed, placeholder = MODULE.clean(contents)

        self.assertEqual(
            removed,
            ["variable_offset_PROBE", "variable_release_stock_case_fan"],
        )
        self.assertTrue(placeholder)
        self.assertNotIn("variable_offset_PROBE", updated)
        self.assertNotIn("variable_release_stock_case_fan", updated)
        self.assertNotIn("# [cartographer touch]", updated)
        self.assertIn("variable_offset_PLA: 0.03", updated)
        self.assertIn("variable_carto_touch_calibrate_start: 2000", updated)
        self.assertIn("[cartographer touch]\nmax_noisy_samples: 4", updated)

    def test_does_not_remove_similarly_named_values_outside_start_vars(self):
        contents = (
            "[gcode_macro USER_SETTINGS]\r\n"
            "variable_offset_PROBE: 7\r\n"
            "[gcode_macro _START_PRINT_VARS]\r\n"
            "variable_offset_DEFAULT: 0.02\r\n"
            "gcode:\r\n"
        )

        updated, removed, placeholder = MODULE.clean(contents)

        self.assertEqual(updated, contents)
        self.assertEqual(removed, [])
        self.assertFalse(placeholder)

    def test_file_update_preserves_existing_cartographer_value(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "overrides.cfg"
            path.write_text(
                "[gcode_macro _START_PRINT_VARS]\n"
                "variable_release_stock_case_fan: 0\n"
                "gcode:\n\n"
                "[cartographer touch]\n"
                "max_noisy_samples: 6\n",
                encoding="utf-8",
            )

            with mock.patch.object(MODULE.sys, "argv", ["cleanup", str(path)]):
                self.assertEqual(MODULE.main(), 0)

            updated = path.read_text(encoding="utf-8")
            self.assertNotIn("variable_release_stock_case_fan", updated)
            self.assertIn("max_noisy_samples: 6", updated)


if __name__ == "__main__":
    unittest.main()
