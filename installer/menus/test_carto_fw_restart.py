"""Structural checks for the post-Cartographer-flash restart workflow."""

import pathlib
import os
import shutil
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
BASH = shutil.which("bash") or "C:/Program Files/Git/bin/bash.exe"


class CartographerFirmwareRestartTests(unittest.TestCase):
    def test_successful_flash_runs_protected_restart(self):
        script = (ROOT / "installer/menus/carto_fw.sh").read_text(encoding="utf-8")
        success = script.index('if [ "$flash_status" -eq 0 ]')
        restart = script.index('sh "$INSTALLER_DIR/scripts/klippy_code_restart.sh"', success)
        cancelled = script.index('elif [ "$flash_status" -eq 2 ]', success)
        self.assertLess(restart, cancelled)

    def test_clean_abort_has_distinct_status(self):
        flasher = (ROOT / "features/cartographer/firmware/flash.py").read_text(encoding="utf-8")
        abort = flasher.index('if fw_path == "ABORT"')
        next_failure = flasher.index("if not fw_path:", abort)
        self.assertIn("return 2", flasher[abort:next_failure])

    def test_cancelled_flash_does_not_enter_failure_recovery(self):
        script = (ROOT / "installer/menus/carto_fw.sh").read_text(encoding="utf-8")
        self.assertIn('elif [ "$flash_status" -eq 2 ]', script)
        self.assertIn("Firmware flashing cancelled; no protected restart was requested.", script)

    def test_preflight_refusal_and_exit_failure_do_not_offer_dfu_or_restart(self):
        script = (ROOT / "installer/menus/carto_fw.sh").read_text(encoding="utf-8")
        for status, next_branch in ((3, 'elif [ "$flash_status" -eq 4 ]'),
                                    (4, '\n    else\n')):
            start = script.index('elif [ "$flash_status" -eq %d ]' % status)
            end = script.index(next_branch, start)
            branch = script[start:end]
            self.assertNotIn("carto_fw_dfu_launch", branch)
            self.assertNotIn("scripts/firmware_restart.sh", branch)
            self.assertNotIn("scripts/klippy_code_restart.sh", branch)
            self.assertNotIn("confirm ", branch)


@unittest.skipUnless(pathlib.Path(BASH).exists(), "bash required")
class CartographerFirmwareMenuTests(unittest.TestCase):
    def launch(self, status, usb_state="Cartographer runtime USB detected (1d50:614e)"):
        script = '''
. "$INSTALLER_DIR/installer/menus/carto_fw.sh"
clear() { :; }
c_yellow() { printf '%s' "$1"; }
c_green() { printf '%s' "$1"; }
c_red() { printf '%s' "$1"; }
info() { printf '%s\n' "$1"; }
warn() { printf '%s\n' "$1"; }
press_enter() { :; }
ensure_path() { :; }
confirm() { return 0; }
detect_carto_usb_state() { printf '%s' "$USB_STATE"; }
python3() { echo FLASHER_INVOKED; return "$FLASH_STATUS"; }
sh() { printf 'RESTART:%s\n' "$1"; }
carto_fw_dfu_launch() { echo DFU_LAUNCH; }
carto_fw_launch
'''
        result = subprocess.run([BASH, "-c", script], text=True, capture_output=True,
                                env=dict(os.environ, INSTALLER_DIR=ROOT.as_posix(),
                                         FLASH_STATUS=str(status), USB_STATE=usb_state))
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_success_uses_protected_host_reload(self):
        output = self.launch(0)
        self.assertIn("RESTART:", output)
        self.assertIn("scripts/klippy_code_restart.sh", output)
        self.assertNotIn("DFU_LAUNCH", output)

    def test_abort_and_refusals_do_not_restart_or_offer_dfu(self):
        for status in (2, 3, 4):
            with self.subTest(status=status):
                output = self.launch(status)
                self.assertNotIn("RESTART:", output)
                self.assertNotIn("DFU_LAUNCH", output)

    def test_actual_failure_still_offers_explicit_recovery(self):
        output = self.launch(1)
        self.assertIn("DFU_LAUNCH", output)
        self.assertNotIn("RESTART:", output)

    def test_no_connected_probe_does_not_launch_flasher(self):
        output = self.launch(0, usb_state="not detected")
        self.assertNotIn("FLASHER_INVOKED", output)
        self.assertNotIn("RESTART:", output)
        self.assertNotIn("DFU_LAUNCH", output)


if __name__ == "__main__":
    unittest.main()
