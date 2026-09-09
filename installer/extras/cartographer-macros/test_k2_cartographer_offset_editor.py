#!/usr/bin/env python3

import importlib.util
import pathlib
import unittest


MODULE_PATH = pathlib.Path(__file__).with_name("k2_cartographer_offset_editor.py")
SPEC = importlib.util.spec_from_file_location("k2_cartographer_offset_editor", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeGCode:
    def __init__(self):
        self.commands = {}
        self.responses = []
        self.scripts = []

    def register_command(self, name, handler, desc=None):
        self.commands[name] = handler

    def respond_raw(self, message):
        self.responses.append(message)

    def run_script_from_command(self, script):
        self.scripts.append(script)


class FakeConfigFile:
    def __init__(self):
        self.raw_config = {
            "cartographer touch_model custom": {
                "threshold": "2000",
                "speed": "2",
                "z_offset": "-0.070",
            },
            "cartographer scan_model default": {"z_offset": "0"},
            "cartographer touch_model default": {
                "threshold": "2400",
                "speed": "2",
                "z_offset": "-0.060",
            },
            "cartographer touch_model textured_pei": {
                "threshold": "2000",
                "speed": "2",
                "z_offset": "-0.050",
            },
        }
        self.saved = []

    def get_status(self, eventtime):
        return {"config": self.raw_config}

    def set(self, section, option, value):
        self.saved.append((section, option, value))


class FakePrintStats:
    def __init__(self, state="standby"):
        self.state = state

    def get_status(self, eventtime):
        return {"state": self.state}


class FakePrinter:
    def __init__(self, state="standby"):
        self.gcode = FakeGCode()
        self.configfile = FakeConfigFile()
        self.print_stats = FakePrintStats(state)

    def lookup_object(self, name, default=None):
        return getattr(self, name, default)


class FakeConfig:
    def __init__(self, printer):
        self.printer = printer

    def get_printer(self):
        return self.printer


class FakeGCmd:
    def __init__(self, **params):
        self.params = params
        self.info = []

    def get_int(self, name, minval=None, maxval=None):
        value = int(self.params[name])
        if minval is not None and value < minval:
            raise self.error("below minimum")
        if maxval is not None and value > maxval:
            raise self.error("above maximum")
        return value

    def get_float(self, name, minval=None, maxval=None):
        value = float(self.params[name])
        if minval is not None and value < minval:
            raise self.error("below minimum")
        if maxval is not None and value > maxval:
            raise self.error("above maximum")
        return value

    def error(self, message):
        return RuntimeError(message)

    def respond_info(self, message):
        self.info.append(message)


class OffsetEditorTests(unittest.TestCase):
    def make_editor(self, state="standby"):
        printer = FakePrinter(state)
        return MODULE.K2CartographerOffsetEditor(FakeConfig(printer)), printer

    def test_discovers_touch_models_in_plate_order_and_renders_prompt(self):
        editor, printer = self.make_editor()
        editor.cmd_open(FakeGCmd())

        self.assertEqual(
            [model["name"] for model in editor.models],
            ["default", "textured_pei", "custom"],
        )
        output = "\n".join(printer.gcode.responses)
        self.assertIn("// action:prompt_begin Global Z Offsets", output)
        self.assertIn("DEFAULT: -0.060 mm", output)
        self.assertIn("TEXTURED_PEI: -0.050 mm", output)
        self.assertNotIn("scan_model", output)
        self.assertIn("Save & Restart|K2_CARTOGRAPHER_GLOBAL_Z_SAVE", output)

    def test_adjustment_is_staged_and_cancel_discards_it(self):
        editor, printer = self.make_editor()
        editor.cmd_open(FakeGCmd())
        editor.cmd_adjust(FakeGCmd(INDEX=0, DELTA=-0.05))

        self.assertEqual(editor.models[0]["current"], -0.11)
        self.assertIn("DEFAULT: -0.110 mm (changed)", "\n".join(printer.gcode.responses))
        cancel = FakeGCmd()
        editor.cmd_cancel(cancel)
        self.assertIsNone(editor.models)
        self.assertEqual(printer.configfile.saved, [])
        self.assertEqual(printer.gcode.scripts, [])
        self.assertEqual(cancel.info, ["Global Z-offset changes cancelled"])

    def test_positive_adjustment_cannot_exceed_cartographer_limit(self):
        editor, _printer = self.make_editor()
        editor.cmd_open(FakeGCmd())
        editor.cmd_adjust(FakeGCmd(INDEX=0, DELTA=0.05))
        editor.cmd_adjust(FakeGCmd(INDEX=0, DELTA=0.05))
        self.assertEqual(editor.models[0]["current"], 0.0)

    def test_save_updates_native_model_section_then_runs_save_config(self):
        editor, printer = self.make_editor()
        editor.cmd_open(FakeGCmd())
        editor.cmd_adjust(FakeGCmd(INDEX=1, DELTA=-0.01))
        editor.cmd_save(FakeGCmd())

        self.assertEqual(
            printer.configfile.saved,
            [
                (
                    "cartographer touch_model textured_pei",
                    "z_offset",
                    "-0.060",
                )
            ],
        )
        self.assertEqual(printer.gcode.scripts, ["SAVE_CONFIG"])
        self.assertIsNone(editor.models)

    def test_unchanged_save_closes_without_restart(self):
        editor, printer = self.make_editor()
        editor.cmd_open(FakeGCmd())
        save = FakeGCmd()
        editor.cmd_save(save)
        self.assertEqual(printer.gcode.scripts, [])
        self.assertEqual(save.info, ["No Global Z-offset changes to save"])

    def test_open_and_save_are_blocked_during_print(self):
        editor, printer = self.make_editor("printing")
        with self.assertRaisesRegex(RuntimeError, "during a print"):
            editor.cmd_open(FakeGCmd())

        printer.print_stats.state = "standby"
        editor.cmd_open(FakeGCmd())
        printer.print_stats.state = "paused"
        with self.assertRaisesRegex(RuntimeError, "during a print"):
            editor.cmd_save(FakeGCmd())

    def test_reports_when_no_touch_models_exist(self):
        editor, printer = self.make_editor()
        printer.configfile.raw_config = {}
        with self.assertRaisesRegex(RuntimeError, "No saved"):
            editor.cmd_open(FakeGCmd())


if __name__ == "__main__":
    unittest.main()
