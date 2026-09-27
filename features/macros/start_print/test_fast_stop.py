#!/usr/bin/env python3
"""Regression tests for the firmware-gated START_PRINT Fast Stop helper."""

import importlib.util
import pathlib
import unittest


MODULE_PATH = pathlib.Path(__file__).with_name("k2_start_print_fast_stop.py")
SPEC = importlib.util.spec_from_file_location("k2_start_print_fast_stop", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeTemplate:
    def __init__(self):
        self.original_calls = []

    def render(self, context=None):
        return "FIRST\nSECOND\n"

    def run_gcode_from_command(self, context=None):
        self.original_calls.append(context)


class SupportedGCode:
    def __init__(self):
        self.cancel_pending = False
        self.calls = []

    def _process_commands(self, commands, need_ack=True, check_cancel=False):
        self.calls.append((commands, need_ack, check_cancel))


class UnsupportedGCode:
    def _process_commands(self, commands, need_ack=True):
        raise AssertionError("unsupported command loop must not be used")


class FakePrinter:
    def __init__(self, gcode, macro):
        self.objects = {
            "gcode": gcode,
            "gcode_macro START_PRINT": macro,
        }
        self.handlers = {}

    def lookup_object(self, name, default=None):
        return self.objects.get(name, default)

    def register_event_handler(self, event, handler):
        self.handlers[event] = handler

    def config_error(self, message):
        return RuntimeError(message)


class FakeConfig:
    def __init__(self, printer):
        self.printer = printer

    def get_printer(self):
        return self.printer


class StartPrintFastStopTests(unittest.TestCase):
    def make_helper(self, gcode):
        macro = type("Macro", (), {"template": FakeTemplate()})()
        printer = FakePrinter(gcode, macro)
        helper = MODULE.K2StartPrintFastStop(FakeConfig(printer))
        return helper, printer, macro

    def test_supported_creality_api_makes_only_start_print_cancel_aware(self):
        helper, printer, macro = self.make_helper(SupportedGCode())
        other_template = FakeTemplate()

        printer.handlers["klippy:ready"]()
        macro.template.run_gcode_from_command({"params": {}})

        self.assertTrue(helper.active)
        self.assertEqual(
            printer.objects["gcode"].calls,
            [(["FIRST", "SECOND", ""], False, True)],
        )
        other_template.run_gcode_from_command({"other": True})
        self.assertEqual(other_template.original_calls, [{"other": True}])

    def test_missing_creality_cancel_api_leaves_start_print_unchanged(self):
        helper, printer, macro = self.make_helper(UnsupportedGCode())
        original = macro.template.run_gcode_from_command

        printer.handlers["klippy:ready"]()

        self.assertFalse(helper.active)
        self.assertEqual(
            macro.template.run_gcode_from_command.__func__, original.__func__
        )

    def test_ready_handler_is_idempotent(self):
        helper, printer, macro = self.make_helper(SupportedGCode())
        printer.handlers["klippy:ready"]()
        installed = macro.template.run_gcode_from_command

        printer.handlers["klippy:ready"]()

        self.assertIs(macro.template.run_gcode_from_command, installed)

    def test_cancel_state_is_exposed_only_after_firmware_gate_activates(self):
        gcode = SupportedGCode()
        gcode.cancel_pending = True
        helper, printer, _macro = self.make_helper(gcode)

        self.assertFalse(helper.is_cancel_pending())
        printer.handlers["klippy:ready"]()
        self.assertTrue(helper.is_cancel_pending())


if __name__ == "__main__":
    unittest.main()
