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
        self.original_safe_move_z = None
        self.guard_pending = False
        self.printer.register_event_handler('klippy:ready', self._handle_ready)

    def _handle_ready(self):
        if self.original_home_z is not None:
            return
        # Stay inert if a retained include is encountered after a later
        # conversion from stock PR Touch to Cartographer.
        if self.printer.lookup_object('prtouch_v3', None) is None:
            return
        original_home_z = self.gcode.register_command('_HOME_Z', None)
        if original_home_z is None:
            raise self.printer.config_error(
                'PR Touch XY guard requires the stock _HOME_Z command')
        original_safe_move_z = self.gcode.register_command('SAFE_MOVE_Z', None)
        if original_safe_move_z is None:
            self.gcode.register_command('_HOME_Z', original_home_z)
            raise self.printer.config_error(
                'PR Touch XY guard requires the stock SAFE_MOVE_Z command')
        self.original_home_z = original_home_z
        self.original_safe_move_z = original_safe_move_z
        try:
            self.gcode.register_command(
                'SAFE_MOVE_Z', self.cmd_SAFE_MOVE_Z,
                desc='Arm one PR Touch pre-XY clearance move')
            self.gcode.register_command(
                '_HOME_Z', self.cmd_HOME_Z,
                desc='Establish PR Touch Z clearance before homing XY travel')
        except Exception:
            self.gcode.register_command('_HOME_Z', None)
            self.gcode.register_command('SAFE_MOVE_Z', None)
            self.gcode.register_command('_HOME_Z', original_home_z)
            self.gcode.register_command('SAFE_MOVE_Z', original_safe_move_z)
            self.original_home_z = None
            self.original_safe_move_z = None
            raise

    def cmd_SAFE_MOVE_Z(self, gcmd):
        # Arm only after SAFE_MOVE_Z succeeds. The next _HOME_Z consumes the
        # arm so later Z-home passes in the same preparation cannot repeat it.
        self.guard_pending = False
        result = self.original_safe_move_z(gcmd)
        self.guard_pending = True
        return result

    def cmd_HOME_Z(self, gcmd):
        guard_pending = self.guard_pending
        self.guard_pending = False
        toolhead = self.printer.lookup_object('toolhead')
        eventtime = self.printer.get_reactor().monotonic()
        homed_axes = toolhead.get_status(eventtime)['homed_axes']
        current_z = toolhead.get_position()[2]
        if (guard_pending and 'z' in homed_axes
                and current_z < self.clearance_z):
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
