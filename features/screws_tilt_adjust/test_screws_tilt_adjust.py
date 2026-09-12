#!/usr/bin/env python3

import importlib.util
import sys
import types
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("screws_tilt_adjust.py")
PACKAGE = "screws_tilt_adjust_test_package"
sys.modules.setdefault(PACKAGE, types.ModuleType(PACKAGE))
sys.modules.setdefault(PACKAGE + ".probe", types.ModuleType(PACKAGE + ".probe"))
SPEC = importlib.util.spec_from_file_location(
    PACKAGE + ".screws_tilt_adjust", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SafeProbeCoordinateTests(unittest.TestCase):
    def test_stock_probe_keeps_screw_coordinate(self):
        self.assertEqual(
            MODULE.calculate_safe_probe_coordinate(28., 0., 352., 0.),
            28.)

    def test_jamin_offset_keeps_reachable_physical_screw_coordinate(self):
        probe_y = MODULE.calculate_safe_probe_coordinate(
            28., 0., 352., -15.)
        self.assertEqual(probe_y, 28.)
        self.assertEqual(probe_y - (-15.), 43.)

    def test_jimmyv_offset_uses_closest_safe_front_point(self):
        probe_y = MODULE.calculate_safe_probe_coordinate(
            28., 0., 352., 36.)
        self.assertEqual(probe_y, 36.5)
        self.assertEqual(probe_y - 36., .5)

    def test_negative_offset_trims_rear_probe_boundary(self):
        self.assertEqual(
            MODULE.calculate_safe_probe_coordinate(351., 0., 352., -15.),
            336.5)

    def test_impossible_probe_range_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "no reachable range"):
            MODULE.calculate_safe_probe_coordinate(28., 0., 20., 25.)

    def test_bed_access_move_uses_requested_distance(self):
        self.assertEqual(MODULE.calculate_bed_access_z(10., 350.), 210.)

    def test_bed_access_move_stays_inside_z_maximum(self):
        self.assertEqual(MODULE.calculate_bed_access_z(200., 350.), 349.5)


if __name__ == "__main__":
    unittest.main()
