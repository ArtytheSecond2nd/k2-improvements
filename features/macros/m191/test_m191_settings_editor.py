import importlib.util
import pathlib
import tempfile
import unittest


HERE = pathlib.Path(__file__).parent
SPEC = importlib.util.spec_from_file_location(
    "k2_m191_settings_editor", HERE / "k2_m191_settings_editor.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def sample_text():
    return """# user values\n[gcode_macro _M191_VARS]\nvariable_bed_assist_enabled: 1\nvariable_bed_assist_trigger_delta: 3.0\nvariable_bed_assist_bed_target: 105.0\nvariable_bed_assist_degrees_above_commanded: 0.0\nvariable_bed_assist_z_height: 195.0\nvariable_circulation_fan_speed: 25.0\nvariable_chamber_fan_margin: 2.0\nvariable_bed_restore_tolerance: 5.0\nvariable_chamber_wait_max_delta: 5.0\ngcode:\n\n[other]\nvalue: keep\n"""


class ParseAndRewriteTests(unittest.TestCase):
    def test_parses_all_settings(self):
        values = MODULE.parse_settings(sample_text())
        self.assertEqual(values["bed_assist_enabled"], 1.0)
        self.assertEqual(values["bed_assist_z_height"], 195.0)
        self.assertEqual(values["circulation_fan_speed"], 25.0)

    def test_rewrites_only_m191_values(self):
        values = MODULE.parse_settings(sample_text())
        values["bed_assist_enabled"] = 0
        values["bed_assist_z_height"] = 220
        values["circulation_fan_speed"] = 40
        updated = MODULE.rewrite_settings(sample_text(), values)
        self.assertIn("variable_bed_assist_enabled: 0\n", updated)
        self.assertIn("variable_bed_assist_z_height: 220.0\n", updated)
        self.assertIn("variable_circulation_fan_speed: 40.0\n", updated)
        self.assertIn("[other]\nvalue: keep\n", updated)

    def test_enforces_exclusive_and_inclusive_ranges(self):
        self.assertEqual(MODULE.validate_value("bed_assist_trigger_delta", 0), 0)
        with self.assertRaises(ValueError):
            MODULE.validate_value("bed_restore_tolerance", 0)
        with self.assertRaises(ValueError):
            MODULE.validate_value("bed_assist_z_height", 331)
        with self.assertRaises(ValueError):
            MODULE.validate_value("bed_assist_enabled", 0.5)

    def test_formats_integer_and_fractional_values(self):
        self.assertEqual(MODULE.format_value("bed_assist_z_height", 195), "195.0")
        self.assertEqual(MODULE.format_value("bed_assist_z_height", 195.5), "195.5")

    def test_atomic_write_replaces_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "overrides.cfg"
            path.write_text(sample_text())
            MODULE.write_atomic(str(path), "replacement\n")
            self.assertEqual(path.read_text(), "replacement\n")


if __name__ == "__main__":
    unittest.main()
