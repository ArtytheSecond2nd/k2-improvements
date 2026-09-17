"""Preserve M191's chamber-fan ceiling across slicer M141 commands."""


class K2M141Guard:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object("gcode")
        self.reactor = self.printer.get_reactor()
        self.original_m141 = None
        self.printer.register_event_handler("klippy:ready", self._handle_ready)

    def _handle_ready(self):
        if self.original_m141 is not None:
            return
        original = self.gcode.register_command("M141", None)
        if original is None:
            raise self.printer.config_error(
                "k2_m141_guard could not find Creality's original M141 handler"
            )

        self.original_m141 = original
        try:
            self.gcode.register_command(
                "M141",
                self.cmd_M141,
                desc="Set chamber temperature without losing the print exhaust ceiling",
            )
        except Exception:
            self.gcode.register_command("M141", None)
            self.gcode.register_command("M141", self.original_m141)
            self.original_m141 = None
            raise

    def _print_state(self):
        print_stats = self.printer.lookup_object("print_stats")
        return print_stats.get_status(self.reactor.monotonic()).get("state")

    def _chamber_fan_margin(self):
        variables = self.printer.lookup_object("gcode_macro _M191_VARS")
        status = variables.get_status(self.reactor.monotonic())
        return float(status["chamber_fan_margin"])

    def cmd_M141(self, gcmd):
        target = gcmd.get_float("S", None)
        should_restore = (
            target is not None
            and target > 40.0
            and self._print_state() == "printing"
        )

        if should_restore:
            margin = self._chamber_fan_margin()
            if margin < 0.0 or margin > 10.0:
                raise gcmd.error(
                    "M191 chamber_fan_margin must be from 0 to 10 C"
                )

        self.original_m141(gcmd)

        if should_restore:
            self.gcode.run_script_from_command(
                "SET_TEMPERATURE_FAN_TARGET "
                "TEMPERATURE_FAN=chamber_fan TARGET=%.6f"
                % (target + margin)
            )


def load_config(config):
    return K2M141Guard(config)
