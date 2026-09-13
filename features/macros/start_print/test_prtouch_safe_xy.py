#!/usr/bin/env python3
"""Behavior checks for the stock PR Touch pre-XY clearance guard."""

import importlib.util
import pathlib
import unittest


HERE = pathlib.Path(__file__).parent
MODULE_PATH = HERE / "k2_prtouch_safe_xy.py"
INSTALLER = HERE / "install.sh"
SPEC = importlib.util.spec_from_file_location("k2_prtouch_safe_xy", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeReactor:
    def monotonic(self):
        return 12.5


class FakeToolhead:
    def __init__(self, z=20.0, homed="xyz", events=None):
        self.z = z
        self.homed = homed
        self.events = events if events is not None else []
        self.moves = []

    def get_status(self, eventtime):
        return {"homed_axes": self.homed}

    def get_position(self):
        return [225.0, 345.0, self.z, 0.0]

    def manual_move(self, position, speed):
        self.events.append("retreat")
        self.moves.append((position, speed))
        self.z = position[2]

    def wait_moves(self):
        self.events.append("wait")


class FakeGcode:
    def __init__(self, original):
        self.handlers = {"_HOME_Z": original}

    def register_command(self, name, handler, desc=None):
        if handler is None:
            return self.handlers.pop(name, None)
        if name in self.handlers:
            raise RuntimeError("already registered")
        self.handlers[name] = handler


class FakePrinter:
    def __init__(self, toolhead, gcode, prtouch=True):
        self.objects = {"toolhead": toolhead, "gcode": gcode}
        if prtouch:
            self.objects["prtouch_v3"] = object()
        self.events = {}
        self.reactor = FakeReactor()

    def lookup_object(self, name, default=None):
        return self.objects.get(name, default)

    def register_event_handler(self, name, handler):
        self.events[name] = handler

    def get_reactor(self):
        return self.reactor

    def config_error(self, message):
        return RuntimeError(message)


class FakeConfig:
    def __init__(self, printer):
        self.printer = printer

    def get_printer(self):
        return self.printer

    def getfloat(self, name, default, above=None):
        return default


class FakeCommand:
    def __init__(self):
        self.messages = []

    def respond_info(self, message):
        self.messages.append(message)


class PRTouchSafeXYTests(unittest.TestCase):
    def make_guard(self, z=20.0, homed="xyz", prtouch=True):
        events = []

        def original(gcmd):
            events.append("original")

        toolhead = FakeToolhead(z=z, homed=homed, events=events)
        gcode = FakeGcode(original)
        printer = FakePrinter(toolhead, gcode, prtouch=prtouch)
        guard = MODULE.PRTouchSafeXY(FakeConfig(printer))
        guard._handle_ready()
        return guard, toolhead, gcode, events

    def test_retreat_completes_before_original_home_z(self):
        guard, toolhead, gcode, events = self.make_guard(z=21.08)
        command = FakeCommand()
        gcode.handlers["_HOME_Z"](command)
        self.assertEqual(
            toolhead.moves, [([None, None, 30.0, None], 6.0)])
        self.assertEqual(events, ["retreat", "wait", "original"])
        self.assertIn("21.080 -> 30.000", command.messages[0])

    def test_normal_z20_path_also_receives_clearance(self):
        guard, toolhead, gcode, events = self.make_guard(z=20.0)
        gcode.handlers["_HOME_Z"](FakeCommand())
        self.assertEqual(toolhead.z, 30.0)

    def test_clear_position_does_not_move(self):
        guard, toolhead, gcode, events = self.make_guard(z=30.0)
        gcode.handlers["_HOME_Z"](FakeCommand())
        self.assertEqual(toolhead.moves, [])
        self.assertEqual(events, ["original"])

    def test_unhomed_z_is_left_to_stock_homing(self):
        guard, toolhead, gcode, events = self.make_guard(z=0.0, homed="xy")
        gcode.handlers["_HOME_Z"](FakeCommand())
        self.assertEqual(toolhead.moves, [])
        self.assertEqual(events, ["original"])

    def test_cartographer_path_does_not_wrap_home_z(self):
        guard, toolhead, gcode, events = self.make_guard(prtouch=False)
        self.assertIsNone(guard.original_home_z)
        gcode.handlers["_HOME_Z"](FakeCommand())
        self.assertEqual(events, ["original"])

    def test_installer_removes_guard_include_for_cartographer(self):
        installer = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("k2_prtouch_safe_xy.py", installer)
        self.assertIn("k2_prtouch_safe_xy.cfg True", installer)


if __name__ == "__main__":
    unittest.main()
