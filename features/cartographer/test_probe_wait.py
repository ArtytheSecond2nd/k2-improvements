"""Stationary Scan timing regressions; no firmware imports or printer access.

Set K2_CARTOGRAPHER_PLUGIN_SOURCE to a local plugin checkout to also exercise
its actual perform_probe/measure_distance methods against the virtual clock.
"""

import ast
import importlib.util
import logging
import math
import os
from pathlib import Path
import statistics
from types import SimpleNamespace
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "k2_cartographer_probe_wait", HERE / "k2_cartographer_probe_wait.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeToolhead:
    def __init__(self, travel=0.0):
        self.now = 0.0
        self.arrival = travel
        self.homed = True
        self.waits = 0
        self.wait_error = None
        self.on_wait = lambda: None
        self.position = SimpleNamespace(x=5.0, y=190.0, z=2.0)
        self.moves = []

    def is_homed(self, axis):
        return self.homed

    def wait_moves(self):
        self.waits += 1
        if self.wait_error:
            raise self.wait_error
        self.now = max(self.now, self.arrival)
        self.on_wait()

    def get_last_move_time(self):
        return self.arrival

    def get_position(self):
        return self.position

    def move(self, **params):
        self.moves.append(params)
        self.position.z = params["z"]

    def z_probing_move(self, scan, speed):
        self.moves.append({"probe": scan, "speed": speed})


class FakeSession:
    def __init__(self, mcu, predicate):
        self.mcu = mcu
        self.predicate = predicate
        self.items = []

    def __enter__(self):
        return self

    def __exit__(self, *error):
        return False

    def wait_for(self, predicate):
        toolhead = self.mcu.toolhead
        deadline = toolhead.now + 5.0
        # Healthy packets arrive during travel too, but the plugin excludes
        # samples older than get_last_move_time. Advance virtual time only.
        while toolhead.now < deadline:
            toolhead.now += 0.002
            if self.mcu.disconnected:
                raise RuntimeError("Cartographer MCU disconnected during session")
            if self.mcu.samples:
                sample = SimpleNamespace(time=toolhead.now, distance=self.mcu.distance)
                if self.predicate(sample):
                    self.items.append(sample)
            if predicate(self.items):
                return
        raise TimeoutError("Timed out waiting for Cartographer samples after 5.0 seconds")

    def get_items(self):
        return self.items


class FakeMcu:
    def __init__(self, toolhead):
        self.toolhead = toolhead
        self.samples = True
        self.distance = 2.03
        self.disconnected = False
        self.started = []

    def start_session(self, predicate):
        self.started.append(self.toolhead.now)
        return FakeSession(self, predicate)


class FakeScan:
    def __init__(self, toolhead):
        self._toolhead = toolhead
        self._mcu = FakeMcu(toolhead)
        self._config = SimpleNamespace(samples=5, probe_speed=5.0)
        self._axis_twist_compensation = None
        self.probe_height = 2.0
        self.model = object()
        self.calls = 0
        self.last_z_result = None

    def get_model(self):
        if self.model is None:
            raise RuntimeError("Scan model not loaded")
        return self.model

    def calculate_sample_distance_batch(self, samples):
        return [sample.distance for sample in samples]

    def measure_distance(self):
        self.get_model()
        time = self._toolhead.get_last_move_time()
        with self._mcu.start_session(lambda sample: sample.time >= time) as session:
            session.wait_for(lambda samples: len(samples) >= 10)
        return statistics.median(self.calculate_sample_distance_batch(session.get_items()[5:]))

    def perform_probe(self):
        self.calls += 1
        if not self._toolhead.is_homed("z"):
            raise RuntimeError("Z axis must be homed before probing")
        self.measure_distance()
        result = self._toolhead.get_position().z + self.probe_height - self.measure_distance()
        if self._axis_twist_compensation:
            result += self._axis_twist_compensation.get_z_compensation_value(x=5, y=190)
        self.last_z_result = result
        return result

    def query_is_triggered(self, print_time):
        return "query"

    def on_home_end(self, state):
        return "home-end"

    def home_start(self, print_time):
        return "home-start"

    def home_wait(self, print_time):
        return "home-wait"

    def start_session(self):
        return "moving-scan"


class FakePrinter:
    config_error = ValueError

    def __init__(self, scan):
        self.shutdown = False
        self.events = {}
        self.touch = SimpleNamespace(perform_probe=lambda: "touch")
        self.carto = SimpleNamespace(scan_mode=scan, touch_mode=self.touch)

    def lookup_object(self, name, default=None):
        return self.carto if name == "cartographer" else default

    def register_event_handler(self, name, callback):
        self.events[name] = callback

    def is_shutdown(self):
        return self.shutdown


class ProbeWaitTests(unittest.TestCase):
    scan_class = FakeScan

    def setUp(self):
        self.toolhead = FakeToolhead(travel=6.5)
        self.scan = self.scan_class(self.toolhead)
        self.printer = FakePrinter(self.scan)
        self.compat = MODULE.load_config(SimpleNamespace(get_printer=lambda: self.printer))

    def activate(self):
        self.printer.events["klippy:ready"]()

    def test_unpatched_long_travel_reproduces_timeout(self):
        with self.assertRaisesRegex(TimeoutError, "5.0 seconds"):
            self.scan.perform_probe()
        self.assertLess(self.toolhead.now, self.toolhead.arrival)

    def test_long_travel_finishes_before_first_sample_deadline(self):
        self.activate()
        self.assertAlmostEqual(self.scan.perform_probe(), 1.97)
        self.assertEqual(self.toolhead.waits, 1)
        self.assertEqual(self.scan._mcu.started[0], 6.5)
        self.assertLess(self.toolhead.now - self.toolhead.arrival, 0.1)
        self.assertEqual(self.toolhead.moves, [])

    def test_missing_samples_still_timeout_five_seconds_after_arrival(self):
        self.scan._mcu.samples = False
        self.activate()
        with self.assertRaisesRegex(TimeoutError, "5.0 seconds"):
            self.scan.perform_probe()
        self.assertAlmostEqual(self.toolhead.now, 11.5, delta=0.003)
        self.assertEqual(self.scan._mcu.started, [6.5])

    def test_no_queued_motion_preserves_numeric_result(self):
        self.toolhead.arrival = 0.0
        expected = self.scan.perform_probe()
        self.toolhead.now = 0.0
        self.activate()
        self.assertEqual(self.scan.perform_probe(), expected)

    def test_offsets_and_axis_twist_remain_in_original_calculation(self):
        self.scan._axis_twist_compensation = SimpleNamespace(
            get_z_compensation_value=lambda **kwargs: -0.17)
        original_model = self.scan.model
        self.activate()
        self.assertAlmostEqual(self.scan.perform_probe(), 1.8)
        self.assertIs(self.scan.model, original_model)

    def test_unhomed_fails_without_waiting_or_sampling(self):
        self.toolhead.homed = False
        self.activate()
        with self.assertRaisesRegex(RuntimeError, "must be homed"):
            self.scan.perform_probe()
        self.assertEqual(self.toolhead.waits, 0)
        self.assertEqual(self.scan._mcu.started, [])

    def test_missing_model_fails_before_waiting_or_sampling(self):
        self.scan.model = None
        self.activate()
        with self.assertRaisesRegex(RuntimeError, "model not loaded"):
            self.scan.perform_probe()
        self.assertEqual(self.toolhead.waits, 0)
        self.assertEqual(self.scan._mcu.started, [])

    def test_shutdown_during_motion_wait_never_resumes_probe(self):
        self.toolhead.on_wait = lambda: setattr(self.printer, "shutdown", True)
        self.activate()
        with self.assertRaisesRegex(RuntimeError, "shutdown"):
            self.scan.perform_probe()
        self.assertEqual(self.scan._mcu.started, [])
        self.assertEqual(self.toolhead.moves, [])

    def test_existing_shutdown_does_not_wait_or_probe(self):
        self.printer.shutdown = True
        self.activate()
        with self.assertRaisesRegex(RuntimeError, "shutdown"):
            self.scan.perform_probe()
        self.assertEqual(self.toolhead.waits, 0)
        self.assertEqual(self.scan._mcu.started, [])

    def test_motion_wait_error_propagates_without_sampling(self):
        self.toolhead.wait_error = RuntimeError("Move interrupted")
        self.activate()
        with self.assertRaisesRegex(RuntimeError, "Move interrupted"):
            self.scan.perform_probe()
        self.assertEqual(self.scan._mcu.started, [])

    def test_disconnect_after_arrival_is_not_hidden(self):
        self.toolhead.on_wait = lambda: setattr(self.scan._mcu, "disconnected", True)
        self.activate()
        with self.assertRaisesRegex(RuntimeError, "disconnected"):
            self.scan.perform_probe()
        self.assertEqual(self.toolhead.moves, [])

    def test_only_stationary_scan_entry_point_is_wrapped(self):
        names = ("measure_distance", "start_session", "query_is_triggered",
                 "home_start", "home_wait", "on_home_end")
        originals = {name: getattr(self.scan, name) for name in names}
        touch = self.printer.touch.perform_probe
        self.activate()
        for name, original in originals.items():
            self.assertEqual(getattr(self.scan, name), original, name)
        self.assertIs(self.printer.touch.perform_probe, touch)

    def test_activation_is_idempotent(self):
        self.activate()
        original = self.compat.original_perform_probe
        self.activate()
        self.assertEqual(self.compat.original_perform_probe, original)
        self.scan.perform_probe()
        self.assertEqual(self.toolhead.waits, 1)
        self.assertTrue(self.compat.get_status(0)["installed"])

    def test_other_scan_instances_are_not_modified(self):
        other = self.scan_class(FakeToolhead(travel=6.5))
        self.activate()
        with self.assertRaises(TimeoutError):
            other.perform_probe()

    def test_unsupported_interface_fails_configuration(self):
        self.printer.carto.scan_mode = object()
        with self.assertRaisesRegex(ValueError, "supported Cartographer"):
            self.activate()
        self.assertFalse(self.compat.get_status(0)["installed"])

    def test_config_and_installer_install_the_hook_before_protected_restart(self):
        config = (HERE / "cartographer.cfg").read_text(encoding="utf-8")
        installer = (HERE / "install.sh").read_text(encoding="utf-8")
        self.assertIn("[k2_cartographer_probe_wait]", config)
        self.assertIn("~/klipper/klippy/extras/k2_cartographer_probe_wait.pyc", installer)
        self.assertIn("~/klipper/klippy/extras/__pycache__/k2_cartographer_probe_wait.*.pyc", installer)
        self.assertLess(installer.index("ln -sf ${SCRIPT_DIR}/k2_cartographer_probe_wait.py"),
                        installer.rindex("scripts/klippy_code_restart.sh"))


def load_real_scan_methods():
    """Extract the actual pure-Python methods without loading host adapters.

    Only the hardware/session and batch-distance interfaces are faked. The
    movement decisions, sample-time filter, sample count and result formula
    executed by these tests come unchanged from the installed plugin source.
    """
    source = Path(os.environ["K2_CARTOGRAPHER_PLUGIN_SOURCE"])
    tree = ast.parse((source / "src/cartographer/probe/scan_mode.py").read_text(encoding="utf-8"))
    scan = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ScanMode")
    methods = [node for node in scan.body if isinstance(node, ast.FunctionDef)
               and node.name in ("perform_probe", "measure_distance")]
    if len(methods) != 2:
        raise AssertionError("Expected supported plugin Scan methods")
    for method in methods:
        method.decorator_list = []
    namespace = {"math": math, "logger": logging.getLogger(__name__),
                 "np": SimpleNamespace(median=statistics.median)}
    unit = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
                            *methods], type_ignores=[])
    exec(compile(ast.fix_missing_locations(unit), str(source / "src/cartographer/probe/scan_mode.py"), "exec"),
         namespace)
    return type("RealScanMethods", (FakeScan,), {
        name: namespace[name] for name in ("perform_probe", "measure_distance")})


if os.environ.get("K2_CARTOGRAPHER_PLUGIN_SOURCE"):
    class RealPluginProbeWaitTests(ProbeWaitTests):
        scan_class = load_real_scan_methods()

        def test_original_z_probe_approach_is_retained(self):
            self.scan._mcu.distance = 3.0
            self.activate()
            self.assertAlmostEqual(self.scan.perform_probe(), 1.0)
            self.assertEqual(len(self.toolhead.moves), 1)
            self.assertIs(self.toolhead.moves[0]["probe"], self.scan)
            self.assertEqual(self.toolhead.moves[0]["speed"], 5.0)

        def test_original_retract_and_its_motion_wait_are_retained(self):
            self.toolhead.position.z = 1.0
            self.activate()
            self.assertAlmostEqual(self.scan.perform_probe(), 1.97)
            self.assertEqual(self.toolhead.moves, [{"z": 2.0, "speed": 5.0}])
            self.assertEqual(self.toolhead.waits, 2)


if __name__ == "__main__":
    unittest.main()
