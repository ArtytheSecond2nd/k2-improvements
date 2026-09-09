#!/usr/bin/env python3
"""Static checks for firmware-scoped macro compatibility."""

import pathlib
import unittest


DIRECTORY = pathlib.Path(__file__).parent
CONFIG = DIRECTORY / "firmware_11313.cfg"
CONFIG_1152 = DIRECTORY / "firmware_1152.cfg"
INSTALLER = DIRECTORY / "install.sh"


class FirmwareCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = CONFIG.read_text(encoding="utf-8")
        cls.config_1152 = CONFIG_1152.read_text(encoding="utf-8")
        cls.installer = INSTALLER.read_text(encoding="utf-8")

    def test_missing_temperature_fan_switch_has_safe_noop(self):
        self.assertIn(
            "[gcode_macro SET_TEMPERATURE_FAN_SWITCH]", self.config
        )
        self.assertIn("G4 P0", self.config)
        self.assertNotIn("SET_PIN", self.config)
        self.assertNotIn("SET_TEMPERATURE_FAN_TARGET", self.config)

    def test_case_fan_release_is_managed_for_both_validated_firmwares(self):
        for config in (self.config, self.config_1152):
            self.assertIn("[gcode_macro _FIRMWARE_COMPAT_K2]", config)
            self.assertIn("variable_release_stock_case_fan: 1", config)

    def test_compatibility_include_is_limited_to_11313(self):
        self.assertIn('[ "$PRINTER_FW" = "1.1.3.13" ]', self.installer)
        self.assertIn("main.cfg firmware_11313.cfg\n", self.installer)
        self.assertIn("main.cfg firmware_11313.cfg True", self.installer)
        self.assertIn('[ "$PRINTER_FW" = "1.1.5.2" ]', self.installer)
        self.assertIn("main.cfg firmware_1152.cfg\n", self.installer)
        self.assertIn("main.cfg firmware_1152.cfg True", self.installer)
        self.assertNotIn("set_case_fan_compat.sh", self.installer)


if __name__ == "__main__":
    unittest.main()
