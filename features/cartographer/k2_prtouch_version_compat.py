"""Report PR Touch v3 compatibility to Creality's master-server.

Creality's K2 Plus master-server selects its complete pre-file preparation
path from the ``prtouch_v3`` section in Klipper's reported config status.
Cartographer removes the physical PR Touch driver, so this compatibility
layer reports an empty synthetic section while Klipper is connecting.

It does not add a real PR Touch configuration section, import the driver,
register a probe, claim a pin, or issue G-code.
"""

import logging


LOG_PREFIX = "[K2_PRTOUCH_VERSION_COMPAT]"
SYNTHETIC_SECTION = "prtouch_v3"


class K2PRTouchVersionCompat:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object("gcode")
        self.configfile = None
        self.installed = False
        self.native_section = False
        self.gcode.register_command(
            "K2_PRTOUCH_VERSION_COMPAT_STATUS",
            self.cmd_status,
            desc="Show Creality PR Touch version-reporting compatibility status",
        )
        self.printer.register_event_handler("klippy:connect", self._handle_connect)

    def _handle_connect(self):
        cartographer = self.printer.lookup_object("cartographer", None)
        self.configfile = self.printer.lookup_object("configfile", None)
        if cartographer is None or self.configfile is None:
            logging.info(
                "%s inactive; Cartographer or configfile is not loaded",
                LOG_PREFIX,
            )
            return

        raw_config = getattr(self.configfile, "status_raw_config", None)
        settings = getattr(self.configfile, "status_settings", None)
        if not isinstance(raw_config, dict) or not isinstance(settings, dict):
            logging.warning(
                "%s inactive; unsupported Klipper configfile status interface",
                LOG_PREFIX,
            )
            return

        self.native_section = (
            SYNTHETIC_SECTION in raw_config or SYNTHETIC_SECTION in settings
        )
        if self.native_section:
            logging.warning(
                "%s inactive; a real %s configuration section is already reported",
                LOG_PREFIX,
                SYNTHETIC_SECTION,
            )
            return

        # These dictionaries are the source returned by configfile.get_status().
        # Empty section objects satisfy Creality's section-presence check without
        # advertising any options belonging to the physical PR Touch driver.
        raw_config[SYNTHETIC_SECTION] = {}
        settings[SYNTHETIC_SECTION] = {}
        self.installed = True
        logging.info(
            "%s reporting synthetic %s configfile section; no PR Touch driver loaded",
            LOG_PREFIX,
            SYNTHETIC_SECTION,
        )

    def get_status(self, eventtime):
        del eventtime
        reported = False
        if self.configfile is not None:
            raw_config = getattr(self.configfile, "status_raw_config", {})
            settings = getattr(self.configfile, "status_settings", {})
            reported = (
                SYNTHETIC_SECTION in raw_config
                and SYNTHETIC_SECTION in settings
            )
        return {
            "installed": self.installed,
            "reported": reported,
            "native_section": self.native_section,
            "driver_loaded": self.printer.lookup_object(
                SYNTHETIC_SECTION, None
            ) is not None,
        }

    def cmd_status(self, gcmd):
        status = self.get_status(0.0)
        gcmd.respond_info(
            "%s installed=%s reported=%s native_section=%s driver_loaded=%s"
            % (
                LOG_PREFIX,
                status["installed"],
                status["reported"],
                status["native_section"],
                status["driver_loaded"],
            )
        )


def load_config(config):
    return K2PRTouchVersionCompat(config)
