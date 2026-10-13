"""Exercise preflight and bootloader refusal cleanup with USB/services mocked."""

import argparse
import ast
import hashlib
import io
import json
import os
from pathlib import Path
import pathlib
from types import SimpleNamespace
from typing import Optional
import unittest
from unittest.mock import MagicMock, patch


HERE = Path(__file__).resolve().parent


class FlashPreflightTests(unittest.TestCase):
    def setUp(self):
        names = {"plugin_support_error", "v4_620_plugin_supported", "plugin_prepare_idle_error",
                 "prepare_plugin_for_flash", "main", "_main_inner"}
        constants = {"MANAGED_PLUGIN_DIR", "AUDITED_CONSTANTS_SHA256", "V4_620_CHECKSUMS"}
        tree = ast.parse((HERE / "flash.py").read_text(encoding="utf-8"))
        nodes = [node for node in tree.body if
                 isinstance(node, ast.FunctionDef) and node.name in names or
                 isinstance(node, ast.Assign) and any(
                     isinstance(target, ast.Name) and target.id in constants for target in node.targets)]
        self.env = dict(pathlib=pathlib, Optional=Optional, hashlib=hashlib, os=os,
                        json=json, argparse=argparse, __file__=str(HERE / "flash.py"),
                        KLIPPER_VID=1, KLIPPER_PID=2, KATAPULT_VID=3, KATAPULT_PID=4,
                        FlashError=type("FlashError", (Exception,), {}))
        for name in ("console", "Prompt", "subprocess", "time", "Panel", "device_present",
                     "stop_services", "start_services", "enter_bootloader", "USBDevice",
                     "DirectFlasher", "show_banner", "scan_flash_for_version", "wait_for_exit",
                     "prompt_firmware", "_print_unsupported_device"):
            self.env[name] = MagicMock()
        self.env["urllib"] = SimpleNamespace(request=SimpleNamespace(urlopen=MagicMock()))
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "flash.py", "exec"), self.env)
        self.args = SimpleNamespace(firmware=None, check_plugin=False)
        self.env["subprocess"].run.return_value.returncode = 0
        exists = patch.object(Path, "exists", return_value=True)
        self.path_exists = exists.start()
        self.addCleanup(exists.stop)
        self.set_api_status("standby", False)

    def set_api_status(self, state, active):
        response = io.StringIO(json.dumps({"result": {"status": {
            "print_stats": {"state": state}, "virtual_sdcard": {"is_active": active}}}}))
        self.env["urllib"].request.urlopen.return_value.__enter__.return_value = response

    def require_prepare(self, final_error=None):
        self.env["v4_620_plugin_supported"] = MagicMock(return_value=False)
        self.env["plugin_support_error"] = MagicMock(side_effect=["Missing audited plugin", final_error])
        self.env["Prompt"].ask.return_value = "y"

    def test_ready_plugin_needs_no_network_prompt_or_update(self):
        self.env["v4_620_plugin_supported"] = MagicMock(return_value=True)
        self.assertTrue(self.env["prepare_plugin_for_flash"](self.args))
        self.env["Prompt"].ask.assert_not_called()
        self.env["urllib"].request.urlopen.assert_not_called()
        self.env["subprocess"].run.assert_not_called()

    def test_uses_managed_shim_path_not_cached_ssh_home(self):
        self.assertEqual(str(self.env["MANAGED_PLUGIN_DIR"]).replace("\\", "/"),
                         "/mnt/UDISK/root/cartographer3d-plugin")
        with patch.object(Path, "read_bytes", side_effect=FileNotFoundError("missing")):
            error = self.env["plugin_support_error"]()
        self.assertIn("constants.py", error)
        self.assertIn("Cannot read", error)

    def test_audit_normalizes_crlf_and_checks_exact_digest(self):
        with patch.object(Path, "read_bytes", return_value=b"source\r\n"), \
                patch.object(hashlib, "sha256") as digest:
            digest.return_value.hexdigest.return_value = self.env["AUDITED_CONSTANTS_SHA256"]
            self.assertTrue(self.env["v4_620_plugin_supported"]())
            digest.assert_called_once_with(b"source\n")
            digest.return_value.hexdigest.return_value = "wrong"
            self.assertIn("Actual SHA-256: wrong", self.env["plugin_support_error"]())

    def test_preparation_invokes_only_safe_plugin_installer(self):
        self.require_prepare()
        self.assertTrue(self.env["prepare_plugin_for_flash"](self.args))
        command = self.env["subprocess"].run.call_args.args[0]
        self.assertEqual(command, ["sh", str(HERE.parent / "install_plugin.sh"),
                                   str(self.env["MANAGED_PLUGIN_DIR"])])
        for name in ("stop_services", "start_services", "enter_bootloader", "USBDevice"):
            self.env[name].assert_not_called()

    def test_decline_does_not_touch_plugin_or_usb(self):
        self.require_prepare()
        self.env["Prompt"].ask.return_value = "n"
        self.assertFalse(self.env["prepare_plugin_for_flash"](self.args))
        self.env["subprocess"].run.assert_not_called()
        self.env["urllib"].request.urlopen.assert_not_called()

    def test_fresh_checkout_can_be_prepared_before_moonraker_install(self):
        self.require_prepare()
        self.path_exists.return_value = False
        self.assertTrue(self.env["prepare_plugin_for_flash"](self.args))
        self.env["urllib"].request.urlopen.assert_not_called()
        self.env["subprocess"].run.assert_called_once()

    def test_prompt_eof_is_safe_refusal(self):
        self.require_prepare()
        self.env["Prompt"].ask.side_effect = EOFError
        self.assertFalse(self.env["prepare_plugin_for_flash"](self.args))
        self.env["subprocess"].run.assert_not_called()

    def test_failed_git_preparation_never_proceeds(self):
        self.require_prepare()
        self.env["subprocess"].run.return_value.returncode = 1
        self.assertFalse(self.env["prepare_plugin_for_flash"](self.args))
        self.env["enter_bootloader"].assert_not_called()

    def test_successful_clone_must_still_pass_audit(self):
        self.require_prepare(final_error="Unrecognized constants hash")
        self.assertFalse(self.env["prepare_plugin_for_flash"](self.args))
        self.env["enter_bootloader"].assert_not_called()

    def test_printing_paused_or_unknown_state_blocks_preparation(self):
        for state, active in (("printing", True), ("paused", False),
                              ("standby", True), ("unknown", False)):
            with self.subTest(state=state, active=active):
                self.require_prepare()
                self.set_api_status(state, active)
                self.assertFalse(self.env["prepare_plugin_for_flash"](self.args))
                self.env["subprocess"].run.assert_not_called()

    def test_missing_idle_status_blocks_preparation(self):
        self.require_prepare()
        self.env["urllib"].request.urlopen.side_effect = OSError("API unavailable")
        self.assertFalse(self.env["prepare_plugin_for_flash"](self.args))
        self.env["subprocess"].run.assert_not_called()

    def test_explicit_legacy_path_does_not_require_v4_plugin(self):
        self.args.firmware = "CartographerV4_6.0.0_USB_full_8kib_offset.bin"
        self.require_prepare()
        self.assertTrue(self.env["prepare_plugin_for_flash"](self.args))
        self.env["subprocess"].run.assert_not_called()

    def test_preflight_refusal_precedes_alternate_screen_and_usb(self):
        self.env["prepare_plugin_for_flash"] = MagicMock(return_value=False)
        with patch("sys.argv", ["flash.py"]), patch("builtins.print") as output:
            self.assertEqual(self.env["main"](), 3)
        output.assert_not_called()
        for name in ("device_present", "stop_services", "enter_bootloader", "USBDevice"):
            self.env[name].assert_not_called()

    def test_check_plugin_is_read_only(self):
        self.env["plugin_support_error"] = MagicMock(return_value="Missing source")
        self.env["prepare_plugin_for_flash"] = MagicMock()
        with patch("sys.argv", ["flash.py", "--check-plugin"]):
            self.assertEqual(self.env["main"](), 3)
        self.env["prepare_plugin_for_flash"].assert_not_called()
        self.env["device_present"].assert_not_called()

    def test_ready_preflight_enters_ui_only_after_check(self):
        self.env["prepare_plugin_for_flash"] = MagicMock(return_value=True)
        self.env["_main_inner"] = MagicMock(return_value=0)
        with patch("sys.argv", ["flash.py"]), patch("builtins.print"):
            self.assertEqual(self.env["main"](), 0)
        self.env["prepare_plugin_for_flash"].assert_called_once()
        self.env["_main_inner"].assert_called_once()

    def set_bootloader(self, selection=None):
        self.env["device_present"].return_value = object()
        self.env["scan_flash_for_version"].return_value = None
        self.env["prompt_firmware"].return_value = selection
        return self.env["DirectFlasher"].return_value

    def test_selection_refusal_exits_bootloader_without_writing(self):
        flasher = self.set_bootloader()
        self.assertEqual(self.env["_main_inner"](self.args), 3)
        flasher.finish.assert_called_once()
        flasher.flash.assert_not_called()
        flasher.verify.assert_not_called()
        self.env["wait_for_exit"].assert_called_once()
        self.env["start_services"].assert_called_once()

    def test_refusal_exit_failure_has_distinct_no_write_status(self):
        flasher = self.set_bootloader()
        flasher.finish.side_effect = self.env["FlashError"]("exit failed")
        self.assertEqual(self.env["_main_inner"](self.args), 4)
        flasher.flash.assert_not_called()
        self.env["start_services"].assert_called_once()

    def test_explicit_v4_path_cannot_bypass_late_plugin_check(self):
        flasher = self.set_bootloader()
        self.args.firmware = "CartographerV4_6.2.0_USB_full_8kib_offset.bin"
        self.env["v4_620_plugin_supported"] = MagicMock(return_value=False)
        self.env["plugin_support_error"] = MagicMock(return_value="Source changed")
        self.assertEqual(self.env["_main_inner"](self.args), 3)
        flasher.finish.assert_called_once()
        flasher.flash.assert_not_called()

    def test_user_abort_remains_status_two(self):
        flasher = self.set_bootloader(selection="ABORT")
        self.assertEqual(self.env["_main_inner"](self.args), 2)
        flasher.finish.assert_called_once()
        flasher.flash.assert_not_called()

    def test_success_still_writes_verifies_and_finishes(self):
        flasher = self.set_bootloader(selection=Path("legacy.bin"))
        self.assertEqual(self.env["_main_inner"](self.args), 0)
        flasher.flash.assert_called_once()
        flasher.verify.assert_called_once()
        flasher.finish.assert_called_once()

    def test_real_write_failure_remains_recovery_failure(self):
        flasher = self.set_bootloader(selection=Path("legacy.bin"))
        flasher.flash.side_effect = self.env["FlashError"]("write failed")
        self.assertEqual(self.env["_main_inner"](self.args), 1)
        flasher.verify.assert_not_called()
        self.env["start_services"].assert_called_once()


if __name__ == "__main__":
    unittest.main()
