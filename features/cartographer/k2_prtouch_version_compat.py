"""Report PR Touch v3 compatibility to Creality's master-server.

Creality's K2 Plus master-server selects its complete pre-file preparation
path when Klipper advertises a ``prtouch_v3`` object. Cartographer removes the
physical PR Touch driver, so this compatibility layer reports a hardware-free
status object and an empty synthetic config section while Klipper loads its
configuration.  The connect event remains as a fallback for unusual section
ordering.

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
        self.object_registered = False
        self.gcode.register_command(
            "K2_PRTOUCH_VERSION_COMPAT_STATUS",
            self.cmd_status,
            desc="Show Creality PR Touch version-reporting compatibility status",
        )
        self.printer.register_event_handler(
            "configfile:status_built", self._handle_config_status_built
        )
        self.printer.register_event_handler("klippy:connect", self._handle_connect)
        # Creality's master-server may inspect config status as soon as Klippy's
        # API appears during a cold boot.  Waiting for klippy:connect can lose
        # that race and make the service cache the reduced preparation path.
        self._install_compatibility("configuration initialization")

    def _handle_config_status_built(self, configfile):
        self.configfile = configfile
        self._install_compatibility("config status finalization")

    def _handle_connect(self):
        self._install_compatibility("klippy:connect")

    def _install_compatibility(self, stage):
        cartographer = self.printer.lookup_object("cartographer", None)
        self.configfile = self.printer.lookup_object("configfile", None)
        if cartographer is None or self.configfile is None:
            logging.info(
                "%s deferred during %s; Cartographer or configfile is not loaded",
                LOG_PREFIX,
                stage,
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

        native_object = self.printer.lookup_object(SYNTHETIC_SECTION, None)
        if native_object is self:
            # Configfile rebuilds these dictionaries after extras are loaded.
            # Restore the synthetic section at connect time without attempting
            # to register the already-present status object a second time.
            raw_config.setdefault(SYNTHETIC_SECTION, {})
            settings.setdefault(SYNTHETIC_SECTION, {})
            self.object_registered = True
            self.installed = True
            return
        self.native_section = (
            SYNTHETIC_SECTION in raw_config or SYNTHETIC_SECTION in settings
        )
        if self.native_section or native_object is not None:
            logging.warning(
                "%s inactive during %s; a real %s section or object is already reported",
                LOG_PREFIX,
                stage,
                SYNTHETIC_SECTION,
            )
            return

        # These dictionaries are the source returned by configfile.get_status().
        # Empty section objects satisfy Creality's section-presence check without
        # advertising any options belonging to the physical PR Touch driver.
        raw_config[SYNTHETIC_SECTION] = {}
        settings[SYNTHETIC_SECTION] = {}
        self.printer.add_object(SYNTHETIC_SECTION, self)
        self.object_registered = True
        self.installed = True
        logging.info(
            "%s reporting synthetic %s status object during %s; no PR Touch driver loaded",
            LOG_PREFIX,
            SYNTHETIC_SECTION,
            stage,
        )

    def get_status(self, eventtime):
        del eventtime
        config_reported = False
        if self.configfile is not None:
            raw_config = getattr(self.configfile, "status_raw_config", {})
            settings = getattr(self.configfile, "status_settings", {})
            config_reported = (
                SYNTHETIC_SECTION in raw_config
                and SYNTHETIC_SECTION in settings
            )
        reported_object = self.printer.lookup_object(SYNTHETIC_SECTION, None)
        return {
            "installed": self.installed,
            # Object presence is the signal consumed by Creality's service.
            "reported": reported_object is not None,
            "config_reported": config_reported,
            "object_registered": reported_object is self,
            "native_section": self.native_section,
            "driver_loaded": reported_object is not None and reported_object is not self,
        }

    def cmd_status(self, gcmd):
        status = self.get_status(0.0)
        gcmd.respond_info(
            "%s installed=%s reported=%s config_reported=%s object_registered=%s "
            "native_section=%s driver_loaded=%s"
            % (
                LOG_PREFIX,
                status["installed"],
                status["reported"],
                status["config_reported"],
                status["object_registered"],
                status["native_section"],
                status["driver_loaded"],
            )
        )


def load_config(config):
    return K2PRTouchVersionCompat(config)
