#!/usr/bin/env python3
"""Regression checks for bootstrap and installer failure handling."""

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class InstallerFailureSafetyTests(unittest.TestCase):
    def test_better_root_copies_are_rerunnable_and_noninteractive_safe(self):
        scripts = (
            ROOT / "features/better-root/install.sh",
            ROOT / "bootstrap/better-root/install.sh",
        )
        for script in scripts:
            with self.subTest(script=script):
                text = script.read_text(encoding="utf-8")
                self.assertIn("ensure_link /usr/share/klipper klipper", text)
                self.assertIn('elif [ -e "$link_path" ]; then', text)
                self.assertIn("elif [ -t 0 ]; then", text)
                self.assertNotIn(
                    "if grep -qE 'root.*UDISK' /etc/passwd; then\n    exit 0",
                    text,
                )

    def test_entware_copies_stop_when_opkg_fails(self):
        scripts = (
            ROOT / "features/entware/install.sh",
            ROOT / "bootstrap/entware/install.sh",
        )
        for script in scripts:
            with self.subTest(script=script):
                lines = script.read_text(encoding="utf-8").splitlines()
                self.assertIn("set -e", lines[:5])
                self.assertIn(
                    "ln -sf /opt/libexec/sftp-server /usr/libexec/sftp-server",
                    lines,
                )

    def test_abort_homing_propagates_unexpected_patcher_failures(self):
        script = ROOT / "features/abort_homing/install.sh"
        text = script.read_text(encoding="utf-8")
        self.assertIn("unexpected exit code $EXIT_CODE", text)
        self.assertIn('exit "$EXIT_CODE"', text)


if __name__ == "__main__":
    unittest.main()
