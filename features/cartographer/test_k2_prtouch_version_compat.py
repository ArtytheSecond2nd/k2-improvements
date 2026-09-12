import importlib.util
import pathlib
import unittest


MODULE_PATH = pathlib.Path(__file__).with_name("k2_prtouch_version_compat.py")
SPEC = importlib.util.spec_from_file_location(
    "k2_prtouch_version_compat", MODULE_PATH
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeGCode:
    def __init__(self):
        self.commands = {}

    def register_command(self, name, callback, desc=None):
        self.commands[name] = (callback, desc)


class FakeConfigFile:
    def __init__(self):
        self.status_raw_config = {"cartographer": {"mcu": "cartographer"}}
        self.status_settings = {"cartographer": {"mcu": "cartographer"}}

    def get_status(self, eventtime):
        del eventtime
        return {
            "config": self.status_raw_config,
            "settings": self.status_settings,
        }


class FakePrinter:
    def __init__(self, include_cartographer=True, native_section=False):
        configfile = FakeConfigFile()
        if native_section:
            configfile.status_raw_config["prtouch_v3"] = {"speed": "5"}
            configfile.status_settings["prtouch_v3"] = {"speed": 5.0}
        self.objects = {"gcode": FakeGCode(), "configfile": configfile}
        if native_section:
            self.objects["prtouch_v3"] = object()
        if include_cartographer:
            self.objects["cartographer"] = object()
        self.handlers = {}

    def lookup_object(self, name, default=None):
        return self.objects.get(name, default)

    def add_object(self, name, value):
        if name in self.objects:
            raise ValueError("object already registered: %s" % (name,))
        self.objects[name] = value

    def register_event_handler(self, event, callback):
        self.handlers[event] = callback


class FakeConfig:
    def __init__(self, printer):
        self.printer = printer

    def get_printer(self):
        return self.printer


class CompatibilityTests(unittest.TestCase):
    def test_reports_section_without_loading_driver(self):
        printer = FakePrinter()
        compat = MODULE.K2PRTouchVersionCompat(FakeConfig(printer))

        config_status = printer.objects["configfile"].get_status(0)
        self.assertEqual(config_status["config"]["prtouch_v3"], {})
        self.assertEqual(config_status["settings"]["prtouch_v3"], {})
        self.assertIs(printer.objects["prtouch_v3"], compat)
        self.assertEqual(
            compat.get_status(0),
            {
                "installed": True,
                "reported": True,
                "config_reported": True,
                "object_registered": True,
                "native_section": False,
                "driver_loaded": False,
            },
        )

    def test_stays_inactive_without_cartographer(self):
        printer = FakePrinter(include_cartographer=False)
        compat = MODULE.K2PRTouchVersionCompat(FakeConfig(printer))
        printer.handlers["klippy:connect"]()
        self.assertFalse(compat.get_status(0)["reported"])

    def test_refuses_to_mask_native_prtouch_section(self):
        printer = FakePrinter(native_section=True)
        compat = MODULE.K2PRTouchVersionCompat(FakeConfig(printer))
        printer.handlers["klippy:connect"]()
        status = compat.get_status(0)
        self.assertFalse(status["installed"])
        self.assertTrue(status["reported"])
        self.assertFalse(status["object_registered"])
        self.assertTrue(status["native_section"])
        self.assertTrue(status["driver_loaded"])
        self.assertEqual(
            printer.objects["configfile"].status_raw_config["prtouch_v3"],
            {"speed": "5"},
        )

    def test_registers_diagnostic_command(self):
        printer = FakePrinter()
        MODULE.K2PRTouchVersionCompat(FakeConfig(printer))
        self.assertIn(
            "K2_PRTOUCH_VERSION_COMPAT_STATUS",
            printer.objects["gcode"].commands,
        )

    def test_reports_before_klippy_ready(self):
        printer = FakePrinter()
        compat = MODULE.K2PRTouchVersionCompat(FakeConfig(printer))
        self.assertIn("klippy:connect", printer.handlers)
        self.assertNotIn("klippy:ready", printer.handlers)
        self.assertIs(printer.objects["prtouch_v3"], compat)

    def test_connect_fallback_handles_late_cartographer(self):
        printer = FakePrinter(include_cartographer=False)
        compat = MODULE.K2PRTouchVersionCompat(FakeConfig(printer))
        self.assertFalse(compat.get_status(0)["reported"])

        printer.objects["cartographer"] = object()
        printer.handlers["klippy:connect"]()

        self.assertIs(printer.objects["prtouch_v3"], compat)
        self.assertTrue(compat.get_status(0)["installed"])

    def test_connect_is_idempotent_after_early_registration(self):
        printer = FakePrinter()
        compat = MODULE.K2PRTouchVersionCompat(FakeConfig(printer))

        printer.handlers["klippy:connect"]()

        self.assertIs(printer.objects["prtouch_v3"], compat)
        self.assertTrue(compat.get_status(0)["installed"])

    def test_status_finalization_restores_config_before_connect(self):
        printer = FakePrinter()
        compat = MODULE.K2PRTouchVersionCompat(FakeConfig(printer))
        configfile = printer.objects["configfile"]
        configfile.status_raw_config.clear()
        configfile.status_raw_config["cartographer"] = {"mcu": "cartographer"}
        configfile.status_settings = {
            "cartographer": {"mcu": "cartographer"}
        }

        self.assertFalse(compat.get_status(0)["config_reported"])
        printer.handlers["configfile:status_built"](configfile)

        self.assertEqual(configfile.status_raw_config["prtouch_v3"], {})
        self.assertEqual(configfile.status_settings["prtouch_v3"], {})
        self.assertIs(printer.objects["prtouch_v3"], compat)
        self.assertTrue(compat.get_status(0)["config_reported"])


if __name__ == "__main__":
    unittest.main()
