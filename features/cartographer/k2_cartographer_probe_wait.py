"""Complete queued positioning before Cartographer's stationary Scan probe.

The plugin's sample deadline must cover sensor acquisition, not travel from a
lowered bed. Wrap only this printer's ScanMode.perform_probe; do not wrap the
shared measure_distance/session methods used by homing and moving scans.
"""

import logging


class K2CartographerProbeWait:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.scan = None
        self.original_perform_probe = None
        self.installed = False
        self.printer.register_event_handler("klippy:ready", self._handle_ready)

    def _handle_ready(self):
        if self.installed:
            return
        cartographer = self.printer.lookup_object("cartographer", None)
        scan = getattr(cartographer, "scan_mode", None)
        toolhead = getattr(scan, "_toolhead", None)
        if not all(callable(method) for method in (
                getattr(scan, "perform_probe", None),
                getattr(scan, "get_model", None),
                getattr(toolhead, "is_homed", None),
                getattr(toolhead, "wait_moves", None))):
            raise self.printer.config_error(
                "K2 stationary Scan probe wait requires a supported Cartographer scan_mode")
        self.scan = scan
        self.original_perform_probe = scan.perform_probe
        scan.perform_probe = self._perform_probe
        self.installed = True
        logging.info("K2 Cartographer stationary Scan probe motion wait installed")

    def _perform_probe(self):
        if self.printer.is_shutdown():
            raise RuntimeError("Aborted: printer entered shutdown")
        toolhead = self.scan._toolhead
        # Preserve the original immediate unhomed/model errors without waiting
        # for queued travel. Do not initiate any motion or change probe height.
        if not toolhead.is_homed("z"):
            return self.original_perform_probe()
        self.scan.get_model()
        toolhead.wait_moves()
        # Klipper's wait_moves can return early on shutdown. Never continue
        # into sampling or a probing move in that case.
        if self.printer.is_shutdown():
            raise RuntimeError("Aborted: printer entered shutdown")
        return self.original_perform_probe()

    def get_status(self, eventtime):
        return {"installed": self.installed}


def load_config(config):
    return K2CartographerProbeWait(config)
