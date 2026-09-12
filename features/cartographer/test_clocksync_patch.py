#!/usr/bin/env python3
"""Regression tests for the Klipper clocksync patch installed by Cartographer."""

import importlib.util
import pathlib
import unittest


PATCH = pathlib.Path(__file__).with_name("patches") / "clocksync.py"


def load_patch():
    spec = importlib.util.spec_from_file_location("k2_clocksync_patch", PATCH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ClockSyncPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_patch()

    def test_patch_imports_without_private_modules(self):
        self.assertIsNotNone(self.module.ClockSync)

    def test_clock_conversions_match_klipper_integer_semantics(self):
        sync = self.module.ClockSync.__new__(self.module.ClockSync)
        sync.mcu_freq = 1000.0
        sync.clock_est = (10.0, 2500.0, 1000.0)

        self.assertEqual(sync.print_time_to_clock(1.2349), 1234)
        self.assertEqual(sync.get_clock(10.2349), 2734)


if __name__ == "__main__":
    unittest.main()
