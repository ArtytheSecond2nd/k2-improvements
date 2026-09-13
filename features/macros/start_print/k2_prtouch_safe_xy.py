# Stock PR Touch pre-XY clearance guard
#
# Creality's artificial-Z preparation can stop against the nozzle and report
# an artificial coordinate near Z=20. Its next G28 Z enters the stock _HOME_Z
# macro, which moves XY before homing Z and can drag the nozzle across the bed.
# This wrapper establishes clearance before allowing _HOME_Z to run.

import math


class PRTouchSafeXY:
    MIN_SAFE_Z = 20.0
    ARTIFICIAL_START_TOLERANCE = 0.5
    ARTIFICIAL_TARGET_TOLERANCE = 0.5
    ARTIFICIAL_REFERENCE_GAP = 10.0

    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')
        self.clearance_z = config.getfloat('clearance_z', 30.0, above=0.0)
        self.speed = config.getfloat('speed', 6.0, above=0.0)
        self.position_max = config.getsection('stepper_z').getfloat(
            'position_max')
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

    def _get_recorded_z(self, eventtime, toolhead):
        recorded_z = getattr(toolhead, 'z_pos', None)
        if recorded_z is None:
            print_stats = self.printer.lookup_object('print_stats')
            recorded_z = print_stats.get_status(eventtime).get('z_pos')
        try:
            recorded_z = float(recorded_z)
        except (TypeError, ValueError):
            return None
        return recorded_z if math.isfinite(recorded_z) else None

    def _is_artificial_z_reference(self, start_z, target_z, recorded_z):
        if recorded_z is None:
            return False
        return (
            abs(start_z - self.position_max)
            <= self.ARTIFICIAL_START_TOLERANCE
            and abs(target_z - self.MIN_SAFE_Z)
            <= self.ARTIFICIAL_TARGET_TOLERANCE
            and start_z - recorded_z >= self.ARTIFICIAL_REFERENCE_GAP)

    def cmd_SAFE_MOVE_Z(self, gcmd):
        # Master-server also uses a bare STA=0 command as the stock handler's
        # stop/cleanup acknowledgement. Pass it through before reading DIS,
        # which is intentionally absent from that command. Preserve any arm
        # established by the preceding STA=1 approach for the next _HOME_Z.
        if gcmd.get_int('STA', 0) == 0:
            return self.original_safe_move_z(gcmd)

        # Classify the coordinate state before the stock command moves. The
        # artificial recovery relabels the coarse physical Z as position_max,
        # while toolhead.z_pos / print_stats.z_pos retains the physical record.
        toolhead = self.printer.lookup_object('toolhead')
        eventtime = self.printer.get_reactor().monotonic()
        start_z = toolhead.get_position()[2]
        target_z = start_z + gcmd.get_float('DIS')
        recorded_z = self._get_recorded_z(eventtime, toolhead)
        artificial_z = self._is_artificial_z_reference(
            start_z, target_z, recorded_z)

        # Arm only after an artificial SAFE_MOVE_Z succeeds. The next _HOME_Z
        # consumes the arm so later Z-home passes cannot repeat it.
        self.guard_pending = False
        result = self.original_safe_move_z(gcmd)
        self.guard_pending = artificial_z
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
