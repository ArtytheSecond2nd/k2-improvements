"""Make only the managed START_PRINT macro honor Creality Fast Stop."""

import inspect
import logging


class K2StartPrintFastStop:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object("gcode")
        self.active = False
        self.printer.register_event_handler("klippy:ready", self._handle_ready)

    def _supports_fast_stop(self):
        process_commands = getattr(self.gcode, "_process_commands", None)
        if process_commands is None or not hasattr(self.gcode, "cancel_pending"):
            return False
        try:
            parameters = inspect.signature(process_commands).parameters
        except (TypeError, ValueError):
            return False
        return "check_cancel" in parameters

    def _handle_ready(self):
        if self.active:
            return
        if not self._supports_fast_stop():
            logging.info(
                "START_PRINT Fast Stop inactive: Creality cancel API unavailable"
            )
            return

        macro = self.printer.lookup_object("gcode_macro START_PRINT", None)
        if macro is None or not hasattr(macro, "template"):
            raise self.printer.config_error(
                "START_PRINT Fast Stop requires the managed START_PRINT macro"
            )
        template = macro.template
        if getattr(template, "k2_fast_stop_active", False):
            self.active = True
            return

        def run_cancelable_start_print(context=None):
            script = template.render(context)
            self.gcode._process_commands(
                script.split("\n"), need_ack=False, check_cancel=True
            )

        template.run_gcode_from_command = run_cancelable_start_print
        template.k2_fast_stop_active = True
        self.active = True
        logging.info("START_PRINT Fast Stop enabled")

    def get_status(self, eventtime):
        return {"active": self.active}

    def is_cancel_pending(self):
        """Report Creality Fast Stop only while this gated helper is active."""
        return self.active and bool(getattr(self.gcode, "cancel_pending", False))


def load_config(config):
    return K2StartPrintFastStop(config)
