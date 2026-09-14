#!/usr/bin/env python3
"""Tests for releasing prtouch_v3's conflicting Axis Twist alias."""

import pathlib
import tempfile
import unittest

try:
    from .patch_prtouch_registration import (
        PATCHED_REGISTRATION,
        REGISTRATION,
        patch_file,
    )
except ImportError:
    from patch_prtouch_registration import (
        PATCHED_REGISTRATION,
        REGISTRATION,
        patch_file,
    )


STOCK_SOURCE = """from . import prtouch_v3_wrapper
from . import probe as probes

def load_config(config):
    prtouch = prtouch_v3_wrapper.PRTouchEndstopWrapper(config)
    config.get_printer().add_object('axis_twist_compensation', prtouch)
    config.get_printer().add_object('probe', probes.PrinterProbe(config, prtouch))
    return prtouch
"""


class PRTouchRegistrationPatchTests(unittest.TestCase):
    def make_target(self, directory, source=STOCK_SOURCE):
        target = pathlib.Path(directory) / "prtouch_v3.py"
        target.write_text(source, encoding="utf-8")
        return target

    def test_releases_only_axis_twist_alias_and_keeps_probe_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            target = self.make_target(directory)

            self.assertTrue(patch_file(target))

            patched = target.read_text(encoding="utf-8")
            self.assertNotIn(REGISTRATION, patched)
            self.assertIn(PATCHED_REGISTRATION, patched)
            self.assertIn("add_object('probe'", patched)
            backup = target.with_name(target.name + ".k2-axis-twist.bak")
            self.assertEqual(backup.read_text(encoding="utf-8"), STOCK_SOURCE)

    def test_patch_is_idempotent_and_preserves_original_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            target = self.make_target(directory)
            self.assertTrue(patch_file(target))
            self.assertFalse(patch_file(target))
            backup = target.with_name(target.name + ".k2-axis-twist.bak")
            self.assertEqual(backup.read_text(encoding="utf-8"), STOCK_SOURCE)

    def test_unknown_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            target = self.make_target(directory, "def load_config(config):\n    pass\n")
            with self.assertRaises(RuntimeError):
                patch_file(target)


if __name__ == "__main__":
    unittest.main()
