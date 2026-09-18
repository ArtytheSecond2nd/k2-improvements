import importlib.util
import pathlib
import unittest


HERE = pathlib.Path(__file__).parent
SPEC = importlib.util.spec_from_file_location(
    "k2_m191_circulation", HERE / "k2_m191_circulation.py"
)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class FakeGcode:
    def __init__(self):
        self.commands = {}
        self.scripts = []

    def register_command(self, name, callback, desc=None):
        self.commands[name] = callback

    def run_script_from_command(self, script):
        self.scripts.append(script)


class FakeSensor:
    def __init__(self, temperatures):
        self.temperatures = list(temperatures)
        self.index = 0

    def get_temp(self, eventtime):
        temperature = self.temperatures[min(self.index, len(self.temperatures) - 1)]
        self.index += 1
        return temperature, 0.0


class FakeToolhead:
    def get_last_move_time(self):
        return 0.0


class FakeHeaters:
    heaters = {}


class FakeReactor:
    def monotonic(self):
        return 0.0

    def pause(self, waketime):
        return waketime


class FakePrinter:
    def __init__(self, sensor):
        self.gcode = FakeGcode()
        self.reactor = FakeReactor()
        self.objects = {
            "gcode": self.gcode,
            "heaters": FakeHeaters(),
            "temperature_sensor chamber_temp": sensor,
            "toolhead": FakeToolhead(),
        }

    def get_reactor(self):
        return self.reactor

    def lookup_object(self, name):
        return self.objects[name]

    def get_start_args(self):
        return {}

    def is_shutdown(self):
        return False


class FakeConfig:
    def __init__(self, printer):
        self.printer = printer

    def get_printer(self):
        return self.printer


class FakeCommand:
    def __init__(self, **params):
        self.params = params
        self.messages = []

    def get(self, name):
        return self.params[name]

    def get_int(self, name, minval=None, maxval=None):
        value = int(self.params[name])
        if minval is not None and value < minval:
            raise ValueError(name)
        if maxval is not None and value > maxval:
            raise ValueError(name)
        return value

    def get_float(self, name, default=None, above=None, maxval=None):
        value = float(self.params.get(name, default))
        if above is not None and value <= above:
            raise ValueError(name)
        if maxval is not None and value > maxval:
            raise ValueError(name)
        return value

    def error(self, message):
        return ValueError(message)

    def respond_info(self, message):
        self.messages.append(message)


class CirculationWaitTests(unittest.TestCase):
    def test_cycles_low_high_low_and_stops_when_target_is_reached(self):
        sensor = FakeSensor([20.0, 20.0, 20.0, 20.0, 50.0])
        printer = FakePrinter(sensor)
        controller = module.K2M191Circulation(FakeConfig(printer))
        command = FakeCommand(
            SENSOR="temperature_sensor chamber_temp",
            MINIMUM=50,
            MAXIMUM=55,
            LOW_PWM=38,
            HIGH_PWM=255,
            LOW_SECONDS=2,
            HIGH_SECONDS=1,
        )

        controller.cmd_wait(command)

        self.assertEqual(
            printer.gcode.scripts,
            [
                "M106 S38\nM106 P2 S38",
                "M106 S255\nM106 P2 S255",
                "M106 S38\nM106 P2 S38",
                "M106 S0\nM106 P2 S0",
            ],
        )
        self.assertEqual(
            command.messages,
            [
                "Bed assist circulation changed to high fan speed",
                "Bed assist circulation changed to low fan speed",
            ],
        )

    def test_immediate_target_still_leaves_both_fans_off(self):
        sensor = FakeSensor([50.0])
        printer = FakePrinter(sensor)
        controller = module.K2M191Circulation(FakeConfig(printer))
        command = FakeCommand(
            SENSOR="temperature_sensor chamber_temp",
            MINIMUM=50,
            MAXIMUM=55,
            LOW_PWM=38,
            HIGH_PWM=255,
            LOW_SECONDS=45,
            HIGH_SECONDS=20,
        )

        controller.cmd_wait(command)

        self.assertEqual(
            printer.gcode.scripts,
            ["M106 S38\nM106 P2 S38", "M106 S0\nM106 P2 S0"],
        )


if __name__ == "__main__":
    unittest.main()
