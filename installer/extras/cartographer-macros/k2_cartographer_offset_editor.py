"""Fluidd prompt editor for saved Cartographer Touch-model Z offsets."""

import logging


LOG_PREFIX = "[K2_CARTOGRAPHER_OFFSET_EDITOR]"
MODEL_PREFIX = "cartographer touch_model "
PREFERRED_ORDER = ("default", "textured_pei", "epoxy", "high_temp", "custom")


class K2CartographerOffsetEditor:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object("gcode")
        self.configfile = self.printer.lookup_object("configfile")
        self.models = None

        self.gcode.register_command(
            "K2_CARTOGRAPHER_GLOBAL_Z_OFFSETS",
            self.cmd_open,
            desc="Edit saved Cartographer Touch-model Z offsets",
        )
        self.gcode.register_command(
            "K2_CARTOGRAPHER_GLOBAL_Z_ADJUST", self.cmd_adjust
        )
        self.gcode.register_command(
            "K2_CARTOGRAPHER_GLOBAL_Z_CANCEL", self.cmd_cancel
        )
        self.gcode.register_command(
            "K2_CARTOGRAPHER_GLOBAL_Z_SAVE", self.cmd_save
        )

    @staticmethod
    def _format_offset(value):
        value = round(float(value), 3)
        if value == 0:
            value = 0.0
        return "%.3f" % value

    @staticmethod
    def _safe_text(value):
        return str(value).replace("\r", " ").replace("\n", " ").replace("|", "/")

    @staticmethod
    def _sort_key(model):
        name = model["name"].lower()
        try:
            return (0, PREFERRED_ORDER.index(name))
        except ValueError:
            return (1, name)

    def _printing_or_paused(self):
        print_stats = self.printer.lookup_object("print_stats", None)
        if print_stats is None:
            return False
        state = str(print_stats.get_status(0.0).get("state", "")).lower()
        return state in ("printing", "paused")

    def _load_models(self, gcmd):
        raw_config = self.configfile.get_status(0.0).get("config", {})
        models = []
        for section, options in raw_config.items():
            if not section.lower().startswith(MODEL_PREFIX):
                continue
            name = section[len(MODEL_PREFIX) :].strip()
            if not name or "z_offset" not in options:
                continue
            try:
                offset = round(float(options["z_offset"]), 3)
            except (TypeError, ValueError):
                raise gcmd.error(
                    "Invalid z_offset in [%s]: %s"
                    % (section, options.get("z_offset"))
                )
            models.append(
                {
                    "section": section,
                    "name": name,
                    "original": offset,
                    "current": offset,
                }
            )

        if not models:
            raise gcmd.error("No saved Cartographer Touch models were found")
        models.sort(key=self._sort_key)
        return models

    def _action(self, message):
        self.gcode.respond_raw("// action:%s" % message)

    def _render_prompt(self, replace=False):
        if replace:
            self._action("prompt_end")
        self._action("prompt_begin Global Z Offsets")
        self._action(
            "prompt_text Saved Touch-model offsets. More negative moves the bed farther from the nozzle."
        )
        for index, model in enumerate(self.models):
            changed = " (changed)" if model["current"] != model["original"] else ""
            self._action(
                "prompt_text %s: %s mm%s"
                % (
                    self._safe_text(model["name"].upper()),
                    self._format_offset(model["current"]),
                    changed,
                )
            )
            self._action("prompt_button_group_start")
            for label, delta in (
                ("-0.05", "-0.05"),
                ("-0.01", "-0.01"),
                ("+0.01", "0.01"),
                ("+0.05", "0.05"),
            ):
                self._action(
                    "prompt_button %s|K2_CARTOGRAPHER_GLOBAL_Z_ADJUST INDEX=%d DELTA=%s|secondary"
                    % (label, index, delta)
                )
            self._action("prompt_button_group_end")
        self._action(
            "prompt_footer_button Cancel|K2_CARTOGRAPHER_GLOBAL_Z_CANCEL|error"
        )
        self._action(
            "prompt_footer_button Save & Restart|K2_CARTOGRAPHER_GLOBAL_Z_SAVE|primary"
        )
        self._action("prompt_show")

    def _require_session(self, gcmd):
        if self.models is None:
            raise gcmd.error("Open GLOBAL_Z_OFFSETS before changing or saving values")

    def cmd_open(self, gcmd):
        if self._printing_or_paused():
            raise gcmd.error("Global Z offsets cannot be edited during a print")
        self.models = self._load_models(gcmd)
        self._render_prompt()

    def cmd_adjust(self, gcmd):
        self._require_session(gcmd)
        index = gcmd.get_int("INDEX", minval=0, maxval=len(self.models) - 1)
        delta = gcmd.get_float("DELTA", minval=-0.05, maxval=0.05)
        model = self.models[index]
        adjusted = round(model["current"] + delta, 3)
        # Cartographer Touch models require z_offset <= 0.
        model["current"] = min(0.0, adjusted)
        self._render_prompt(replace=True)

    def cmd_cancel(self, gcmd):
        self._require_session(gcmd)
        self.models = None
        self._action("prompt_end")
        gcmd.respond_info("Global Z-offset changes cancelled")

    def cmd_save(self, gcmd):
        self._require_session(gcmd)
        if self._printing_or_paused():
            raise gcmd.error("Save & Restart is not allowed during a print")

        changed = [
            model for model in self.models if model["current"] != model["original"]
        ]
        if not changed:
            self.models = None
            self._action("prompt_end")
            gcmd.respond_info("No Global Z-offset changes to save")
            return

        for model in changed:
            self.configfile.set(
                model["section"],
                "z_offset",
                self._format_offset(model["current"]),
            )
            logging.info(
                "%s staged [%s] z_offset=%s",
                LOG_PREFIX,
                model["section"],
                self._format_offset(model["current"]),
            )

        self.models = None
        self._action("prompt_end")
        self.gcode.run_script_from_command("SAVE_CONFIG")


def load_config(config):
    return K2CartographerOffsetEditor(config)
