#!/usr/bin/env python3
"""Static checks for the managed START_PRINT configuration."""

import pathlib
import unittest


CONFIG = pathlib.Path(__file__).with_name("start_print.cfg")
MACROS_INSTALLER = CONFIG.parent.parent / "install.sh"


class StartPrintConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = CONFIG.read_text(encoding="utf-8")

    def test_case_fan_release_wraps_native_nozzle_clean(self):
        section = self.config.split(
            "[gcode_macro BOX_NOZZLE_CLEAN]", 1
        )[1].split("[gcode_macro START_PRINT]", 1)[0]
        self.assertIn(
            "rename_existing: _K2_ORIGINAL_BOX_NOZZLE_CLEAN", section
        )
        self.assertIn("_K2_ORIGINAL_BOX_NOZZLE_CLEAN {rawparams}", section)
        self.assertIn("M107 P1", section)

    def test_case_fan_release_applies_to_both_probe_paths(self):
        section = self.config.split(
            "[gcode_macro BOX_NOZZLE_CLEAN]", 1
        )[1].split("[gcode_macro START_PRINT]", 1)[0]
        self.assertIn("DIRECT_CASE_FAN >= 0.999", section)
        self.assertNotIn("'cartographer' not in printer", section)

    def test_case_fan_release_requires_direct_full_speed_request(self):
        section = self.config.split(
            "[gcode_macro BOX_NOZZLE_CLEAN]", 1
        )[1].split("[gcode_macro START_PRINT]", 1)[0]
        self.assertIn('printer["output_pin fan1"].value', section)
        self.assertIn("DIRECT_CASE_FAN >= 0.999", section)

    def test_case_fan_release_preserves_active_chamber_cooling(self):
        section = self.config.split(
            "[gcode_macro BOX_NOZZLE_CLEAN]", 1
        )[1].split("[gcode_macro START_PRINT]", 1)[0]
        self.assertIn('printer["temperature_fan chamber_fan"].speed', section)
        self.assertIn("CHAMBER_COOLING <= 0.0", section)

    def test_case_fan_release_is_runtime_state_gated(self):
        section = self.config.split(
            "[gcode_macro BOX_NOZZLE_CLEAN]", 1
        )[1].split("[gcode_macro START_PRINT]", 1)[0]
        self.assertNotIn("_FIRMWARE_COMPAT_K2", section)
        self.assertNotIn("RELEASE_CASE_FAN", section)
        self.assertNotIn("variable_release_stock_case_fan:", self.config)

    def test_obsolete_probe_switch_is_not_advertised(self):
        self.assertNotIn("variable_offset_PROBE:", self.config)

    def test_case_fan_is_not_continuously_enforced(self):
        self.assertEqual(self.config.count("M107 P1"), 1)
        self.assertNotIn("[delayed_gcode", self.config)

    def test_active_chamber_wait_uses_creality_35c_boundary(self):
        self.assertIn("{% if CHAMBER_TEMP > 35 %}", self.config)
        self.assertNotIn("{% if CHAMBER_TEMP > 40 %}", self.config)

    def test_preheat_applies_fan_margin_for_existing_mesh_path(self):
        self.assertIn(
            "SET_TEMPERATURE_FAN_TARGET TEMPERATURE_FAN=chamber_fan "
            "TARGET={CHAMBER_TEMP + 2.0}",
            self.config,
        )
        self.assertNotIn("M141 S{CHAMBER_TEMP}", self.config)

    def test_preheat_keeps_passive_chamber_heater_off(self):
        active_guard = self.config.index("{% if CHAMBER_TEMP > 35 %}")
        active_heater = self.config.index(
            "SET_HEATER_TEMPERATURE HEATER=chamber_heater "
            "TARGET={CHAMBER_TEMP}",
            active_guard,
        )
        passive_branch = self.config.index("{% else %}", active_heater)
        passive_heater = self.config.index(
            "SET_HEATER_TEMPERATURE HEATER=chamber_heater TARGET=0",
            passive_branch,
        )
        self.assertLess(active_heater, passive_branch)
        self.assertLess(passive_branch, passive_heater)

    def test_optional_material_editor_owns_offset_application(self):
        self.assertIn('"k2_material_z_offset_editor" in printer', self.config)
        self.assertIn('K2_MATERIAL_Z_APPLY MATERIAL="{MATERIAL}"', self.config)
        self.assertEqual(self.config.count("SET_GCODE_OFFSET Z={OFFSET}"), 1)

    def test_material_defaults_start_at_point_zero_five(self):
        for material in ("PLA", "PETG", "ABS", "ASA", "DEFAULT"):
            self.assertIn("variable_offset_%s: 0.05" % material, self.config)

    def test_macro_repair_preserves_plate_surface_wrapper(self):
        installer = MACROS_INSTALLER.read_text(encoding="utf-8")
        capture = installer.index("HAD_SURFACE_WRAPPER=1")
        refresh = installer.index("for sub in start_print m191 bed_mesh overrides")
        restore = installer.index("surface-selection-wrapper/install.sh")
        self.assertLess(capture, refresh)
        self.assertLess(refresh, restore)


if __name__ == "__main__":
    unittest.main()
