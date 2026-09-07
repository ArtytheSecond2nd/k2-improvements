#!/usr/bin/env python3
"""Static checks for PR-Touch commands retained by stock K2 macros."""

import pathlib
import unittest


CONFIG = pathlib.Path(__file__).with_name("cartographer.cfg")


class PRTouchCommandCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = CONFIG.read_text(encoding="utf-8")

    def test_removed_prtouch_commands_are_defined_for_cartographer(self):
        for command in ("PRES_CHECK", "NOZZLE_CLEAR", "NEXT_HOMEZ_NACCU"):
            with self.subTest(command=command):
                section = f"[gcode_macro {command}]"
                self.assertEqual(self.config.count(section), 1)

    def test_compatibility_commands_do_not_issue_motion(self):
        for command in ("PRES_CHECK", "NOZZLE_CLEAR", "NEXT_HOMEZ_NACCU"):
            with self.subTest(command=command):
                section = self.config.split(
                    f"[gcode_macro {command}]", 1
                )[1].split("[gcode_macro ", 1)[0]
                self.assertIn("G4 P0", section)
                self.assertNotIn("G0 ", section)
                self.assertNotIn("G1 ", section)
                self.assertNotIn("G28", section)


if __name__ == "__main__":
    unittest.main()
