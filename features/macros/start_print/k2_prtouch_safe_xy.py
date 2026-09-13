# Stock PR Touch pre-XY clearance guard
#
# Creality's artificial-Z preparation can stop against the nozzle and report
# an artificial coordinate near Z=20. Its next G28 Z enters the stock _HOME_Z
# macro, which moves XY before homing Z and can drag the nozzle across the bed.
# This wrapper establishes clearance before allowing _HOME_Z to run.


class PRTouchSafeXY:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')
        self.clearance_z = config.getfloat('clearance_z', 30.0, above=0.0)
        self.speed = config.getfloat('speed', 6.0, above=0.0)
        self.original_home_z = None
        self.printer.register_event_handler('klippy:ready', self._handle_ready)

    def _handle_ready(self):
        if self.original_home_z is not None:
            return
        # Stay inert if a retained include is encountered after a later
        # conversion from stock PR Touch to Cartographer.
        if self.printer.lookup_object('prtouch_v3', None) is None:
            return
        original = self.gcode.register_command('_HOME_Z', None)
        if original is None:
            raise self.printer.config_error(
                'PR Touch XY guard requires the stock _HOME_Z command')
        self.original_home_z = original
        try:
            self.gcode.register_command(
                '_HOME_Z', self.cmd_HOME_Z,
                desc='Establish PR Touch Z clearance before homing XY travel')
        except Exception:
            self.gcode.register_command('_HOME_Z', original)
            self.original_home_z = None
            raise

    def cmd_HOME_Z(self, gcmd):
        toolhead = self.printer.lookup_object('toolhead')
        eventtime = self.printer.get_reactor().monotonic()
        homed_axes = toolhead.get_status(eventtime)['homed_axes']
        current_z = toolhead.get_position()[2]
        if 'z' in homed_axes and current_z < self.clearance_z:
            gcmd.respond_info(
                '[PRTOUCH_SAFE_XY] Moving Z away from the nozzle before XY '
                'travel: %.3f -> %.3f' % (current_z, self.clearance_z))
            # manual_move fills the None axes from the commanded position and
            # is the native toolhead API for this ordered safety move.
            toolhead.manual_move(
                [None, None, self.clearance_z, None], self.speed)
            toolhead.wait_moves()
        return self.original_home_z(gcmd)


def load_config(config):
    return PRTouchSafeXY(config)
