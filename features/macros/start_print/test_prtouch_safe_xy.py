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
    def __init__(self, z=20.0, recorded_z=None, homed="xyz", events=None):
        self.z = z
        self.z_pos = recorded_z
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
    def __init__(self, original_home_z, original_safe_move_z):
        self.handlers = {
            "_HOME_Z": original_home_z,
            "SAFE_MOVE_Z": original_safe_move_z,
        }

    def register_command(self, name, handler, desc=None):
        if handler is None:
            return self.handlers.pop(name, None)
        if name in self.handlers:
            raise RuntimeError("already registered")
        self.handlers[name] = handler


class FakePrinter:
    def __init__(self, toolhead, gcode, prtouch=True):
        self.objects = {
            "toolhead": toolhead,
            "gcode": gcode,
            "print_stats": FakePrintStats(toolhead),
        }
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

    def getsection(self, name):
        return FakeSection()


class FakeSection:
    def getfloat(self, name):
        return 360.0


class FakePrintStats:
    def __init__(self, toolhead):
        self.toolhead = toolhead

    def get_status(self, eventtime):
        return {"z_pos": self.toolhead.z_pos}


class FakeCommand:
    def __init__(self, distance=-340.0, state=1):
        self.messages = []
        self.distance = distance
        self.state = state

    def respond_info(self, message):
        self.messages.append(message)

    def get_float(self, name):
        if name != "DIS":
            raise KeyError(name)
        if self.distance is None:
            raise AssertionError("DIS must not be read from a bare STA=0 command")
        return self.distance

    def get_int(self, name, default=None):
        if name != "STA":
            raise KeyError(name)
        return self.state


class PRTouchSafeXYTests(unittest.TestCase):
    def make_guard(self, z=360.0, recorded_z=348.62, homed="xyz",
                   prtouch=True):
        events = []

        def original(gcmd):
            events.append("original")

        def original_safe_move_z(gcmd):
            events.append("safe_move_z")

        toolhead = FakeToolhead(
            z=z, recorded_z=recorded_z, homed=homed, events=events)
        gcode = FakeGcode(original, original_safe_move_z)
        printer = FakePrinter(toolhead, gcode, prtouch=prtouch)
        guard = MODULE.PRTouchSafeXY(FakeConfig(printer))
        guard._handle_ready()
        return guard, toolhead, gcode, events

    def arm_guard(self, gcode, distance=-340.0):
        gcode.handlers["SAFE_MOVE_Z"](FakeCommand(distance))

    def test_retreat_completes_before_original_home_z(self):
        guard, toolhead, gcode, events = self.make_guard()
        command = FakeCommand()
        self.arm_guard(gcode)
        toolhead.z = 21.08
        gcode.handlers["_HOME_Z"](command)
        self.assertEqual(
            toolhead.moves, [([None, None, 30.0, None], 6.0)])
        self.assertEqual(
            events, ["safe_move_z", "retreat", "wait", "original"])
        self.assertIn("21.080 -> 30.000", command.messages[0])

    def test_normal_between_print_move_does_not_arm_guard(self):
        guard, toolhead, gcode, events = self.make_guard(
            z=173.003, recorded_z=173.003)
        self.arm_guard(gcode, distance=-153.003)
        toolhead.z = 20.0
        gcode.handlers["_HOME_Z"](FakeCommand())
        self.assertEqual(toolhead.z, 20.0)
        self.assertEqual(toolhead.moves, [])

    def test_home_z_before_safe_move_does_not_use_guard(self):
        guard, toolhead, gcode, events = self.make_guard()
        gcode.handlers["_HOME_Z"](FakeCommand())
        self.assertEqual(toolhead.moves, [])
        self.assertEqual(events, ["original"])

    def test_only_first_home_z_after_safe_move_can_use_guard(self):
        guard, toolhead, gcode, events = self.make_guard()
        self.arm_guard(gcode)
        toolhead.z = 20.5
        gcode.handlers["_HOME_Z"](FakeCommand())
        toolhead.z = 5.0
        gcode.handlers["_HOME_Z"](FakeCommand())
        gcode.handlers["_HOME_Z"](FakeCommand())
        self.assertEqual(
            toolhead.moves, [([None, None, 30.0, None], 6.0)])
        self.assertEqual(events.count("retreat"), 1)
        self.assertEqual(events.count("original"), 3)

    def test_next_safe_move_rearms_guard(self):
        guard, toolhead, gcode, events = self.make_guard()
        self.arm_guard(gcode)
        toolhead.z = 20.0
        gcode.handlers["_HOME_Z"](FakeCommand())
        toolhead.z = 360.0
        toolhead.z_pos = 348.0
        self.arm_guard(gcode)
        toolhead.z = 21.0
        gcode.handlers["_HOME_Z"](FakeCommand())
        self.assertEqual(len(toolhead.moves), 2)

    def test_bare_cleanup_passes_through_and_preserves_pending_guard(self):
        guard, toolhead, gcode, events = self.make_guard()
        self.arm_guard(gcode)
        gcode.handlers["SAFE_MOVE_Z"](
            FakeCommand(distance=None, state=0))
        toolhead.z = 20.5
        gcode.handlers["_HOME_Z"](FakeCommand())
        self.assertEqual(
            toolhead.moves, [([None, None, 30.0, None], 6.0)])
        self.assertEqual(
            events, ["safe_move_z", "safe_move_z", "retreat", "wait", "original"])

    def test_ai_followup_approach_preserves_pending_guard(self):
        guard, toolhead, gcode, events = self.make_guard()
        self.arm_guard(gcode)
        toolhead.z = 21.0125
        toolhead.z_pos = 21.0125
        self.arm_guard(gcode, distance=-1.0125)
        toolhead.z = 20.935
        gcode.handlers["_HOME_Z"](FakeCommand())
        self.assertEqual(
            toolhead.moves, [([None, None, 30.0, None], 6.0)])
        self.assertEqual(
            events, ["safe_move_z", "safe_move_z", "retreat", "wait", "original"])

    def test_clear_position_does_not_move(self):
        guard, toolhead, gcode, events = self.make_guard()
        self.arm_guard(gcode)
        toolhead.z = 30.0
        gcode.handlers["_HOME_Z"](FakeCommand())
        self.assertEqual(toolhead.moves, [])
        self.assertEqual(events, ["safe_move_z", "original"])

    def test_unhomed_z_is_left_to_stock_homing(self):
        guard, toolhead, gcode, events = self.make_guard(homed="xy")
        self.arm_guard(gcode)
        toolhead.z = 0.0
        gcode.handlers["_HOME_Z"](FakeCommand())
        self.assertEqual(toolhead.moves, [])
        self.assertEqual(events, ["safe_move_z", "original"])

    def test_cartographer_path_does_not_wrap_home_z(self):
        guard, toolhead, gcode, events = self.make_guard(prtouch=False)
        self.assertIsNone(guard.original_home_z)
        gcode.handlers["_HOME_Z"](FakeCommand())
        self.assertEqual(events, ["original"])

    def test_artificial_start_without_recorded_z_gap_does_not_arm(self):
        guard, toolhead, gcode, events = self.make_guard(
            z=360.0, recorded_z=355.0)
        self.arm_guard(gcode)
        toolhead.z = 21.0
        gcode.handlers["_HOME_Z"](FakeCommand())
        self.assertEqual(toolhead.moves, [])

    def test_position_max_start_with_non_z20_target_does_not_arm(self):
        guard, toolhead, gcode, events = self.make_guard()
        self.arm_guard(gcode, distance=-330.0)
        toolhead.z = 30.0
        gcode.handlers["_HOME_Z"](FakeCommand())
        self.assertEqual(toolhead.moves, [])

    def test_installer_removes_guard_include_for_cartographer(self):
        installer = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("k2_prtouch_safe_xy.py", installer)
        self.assertIn("k2_prtouch_safe_xy.cfg True", installer)


if __name__ == "__main__":
    unittest.main()
