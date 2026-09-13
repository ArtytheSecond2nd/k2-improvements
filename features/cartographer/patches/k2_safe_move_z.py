# Creality K2 Plus SAFE_MOVE_Z compatibility for Cartographer
#
# The stock prtouch_v3 extension owns SAFE_MOVE_Z and reports the completed
# travel through virtual_sdcard.run_dis.  Creality's master-server waits for
# that status field before it continues preparing a consecutive print.
# Cartographer replaces prtouch_v3, so both parts of that contract must be
# supplied here.
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging
import math


class K2SafeMoveZ:
    MIN_SAFE_Z = 20.0
    MIN_SAFE_Z_TOLERANCE = 0.25
    COMPLETION_TOLERANCE = 0.05
    ARTIFICIAL_START_TOLERANCE = 0.5
    ARTIFICIAL_TARGET_TOLERANCE = 0.5
    ARTIFICIAL_REFERENCE_GAP = 10.0
    ARTIFICIAL_BACKUP_CLEARANCE = 1.0
    ARTIFICIAL_TRIGGER_RETREAT = 10.0

    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')

        printer_config = config.getsection('printer')
        self.max_z_velocity = printer_config.getfloat(
            'max_z_velocity', above=0.0)
        stepper_z_config = config.getsection('stepper_z')
        self.position_min = stepper_z_config.getfloat(
            'position_min', 0.0)
        self.position_max = stepper_z_config.getfloat('position_max')

        self.gcode.register_command(
            'SAFE_MOVE_Z', self.cmd_SAFE_MOVE_Z,
            desc=self.cmd_SAFE_MOVE_Z_help)

    cmd_SAFE_MOVE_Z_help = (
        "Handle Creality's guarded inter-print safe Z move")

    def _require_idle(self, gcmd):
        print_stats = self.printer.lookup_object('print_stats')
        eventtime = self.printer.get_reactor().monotonic()
        state = print_stats.get_status(eventtime).get('state', '')
        if state in ('printing', 'paused'):
            raise gcmd.error(
                '[SAFE_MOVE_Z] Refusing inter-print move while a print is '
                'active')

    def _get_recorded_z(self, eventtime, toolhead):
        # Creality's K2 toolhead keeps a separately recorded Z value and
        # mirrors it through print_stats.z_pos.  SET_POSITION changes the
        # commanded coordinate but intentionally does not change this value.
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

    def _get_scan_endstop(self, gcmd):
        cartographer = self.printer.lookup_object('cartographer', None)
        scan_mode = getattr(cartographer, 'scan_mode', None)
        if scan_mode is None or not scan_mode.is_ready:
            raise gcmd.error(
                '[SAFE_MOVE_Z] Cartographer scan model is not ready')

        klipper_mcu = getattr(getattr(cartographer, 'mcu', None),
                              'klipper_mcu', None)
        if (klipper_mcu is None
                or getattr(klipper_mcu, 'non_critical_disconnected', False)):
            raise gcmd.error(
                '[SAFE_MOVE_Z] Cartographer MCU is disconnected')

        # Delay the plugin import until the [cartographer] object has loaded
        # its source tree into sys.path.
        from cartographer.adapters.klipper.endstop import KlipperEndstop
        return KlipperEndstop(cartographer.mcu, scan_mode)

    def _guarded_move(self, gcmd, toolhead, target_z, speed):
        # This is deliberately an optional-endstop move.  A normal
        # between-print move reaches its Z=20 endpoint without seeing the bed;
        # a bad coordinate can instead be interrupted by Cartographer in the
        # MCU homing path.
        from extras.homing import HomingMove

        scan_endstop = self._get_scan_endstop(gcmd)
        move_target = toolhead.get_position()
        move_target[2] = target_z
        hmove = HomingMove(
            self.printer, [(scan_endstop, 'cartographer')])
        hmove.homing_move(
            move_target, speed, probe_pos=True, check_triggered=False)

        end_z = toolhead.get_position()[2]
        triggered = end_z > target_z + self.COMPLETION_TOLERANCE
        return end_z, triggered

    def _retreat_after_trigger(self, gcmd, toolhead, trigger_z, speed):
        # Increasing K2 Z lowers the bed away from the nozzle.  Use a relative
        # retreat because Creality's artificial coordinate is intentionally
        # not a trustworthy physical absolute position.
        retreat_z = min(
            self.position_max,
            trigger_z + self.ARTIFICIAL_TRIGGER_RETREAT)
        retreat_target = toolhead.get_position()
        retreat_target[2] = retreat_z
        toolhead.move(retreat_target, speed)
        toolhead.wait_moves()
        end_z = toolhead.get_position()[2]
        if abs(end_z - retreat_z) > self.COMPLETION_TOLERANCE:
            raise gcmd.error(
                '[SAFE_MOVE_Z] Cartographer-trigger retreat stopped at '
                'Z=%.3f; expected Z=%.3f' % (end_z, retreat_z))
        return end_z

    def cmd_SAFE_MOVE_Z(self, gcmd):
        state = gcmd.get_int('STA', 0)
        if state == 0:
            gcmd.respond_info(
                '[SAFE_MOVE_Z] Stop/cleanup request acknowledged')
            return
        if state != 1:
            raise gcmd.error(
                '[SAFE_MOVE_Z] Unsupported STA=%d' % (state,))

        distance = gcmd.get_float('DIS')
        speed = gcmd.get_float('SPD')
        if not math.isfinite(distance):
            raise gcmd.error('[SAFE_MOVE_Z] DIS must be finite')
        if distance >= 0.0:
            raise gcmd.error(
                '[SAFE_MOVE_Z] Refusing non-negative travel %.3fmm' %
                (distance,))
        if (not math.isfinite(speed) or speed <= 0.0
                or speed > self.max_z_velocity):
            raise gcmd.error(
                '[SAFE_MOVE_Z] Refusing invalid speed %.3fmm/s' % (speed,))

        self._require_idle(gcmd)
        eventtime = self.printer.get_reactor().monotonic()
        toolhead = self.printer.lookup_object('toolhead')
        if 'z' not in toolhead.get_status(eventtime).get('homed_axes', ''):
            raise gcmd.error(
                '[SAFE_MOVE_Z] Refusing move because Z is not homed')

        start_z = toolhead.get_position()[2]
        target_z = start_z + distance
        # Z=20 is the closest observed safe endpoint to the nozzle.  c440x
        # calculates DIS before this command is executed, so cancellation
        # cleanup or another queued move can make the eventual endpoint higher
        # than 20.  A higher endpoint leaves more bed/nozzle clearance and is
        # safe; an endpoint below the Z=20 floor is not.
        if target_z < self.MIN_SAFE_Z - self.MIN_SAFE_Z_TOLERANCE:
            raise gcmd.error(
                '[SAFE_MOVE_Z] Refusing target below safe Z floor: Z=%.3f' %
                (target_z,))
        if target_z < self.position_min or target_z > self.position_max:
            raise gcmd.error(
                '[SAFE_MOVE_Z] Target Z=%.3f is outside machine limits' %
                (target_z,))

        recorded_z = self._get_recorded_z(eventtime, toolhead)
        artificial_z = self._is_artificial_z_reference(
            start_z, target_z, recorded_z)

        guarded_target_z = target_z
        if artificial_z:
            # ZDOWN records the coarse physical reference before c440x
            # relabels that same location as Z=position_max.  Retain a final
            # mechanical fallback just below Cartographer's normal 2 mm scan
            # trigger.  If scan detection fails, stop here and report a fault
            # instead of completing the unsafe requested travel.
            guarded_target_z = max(
                target_z,
                start_z - max(
                    0.0, recorded_z - self.ARTIFICIAL_BACKUP_CLEARANCE))

        virtual_sdcard = self.printer.lookup_object('virtual_sdcard')
        # Clear the prior operation before starting.  master-server polls this
        # field and must not mistake a previous safe move for this one.
        virtual_sdcard.run_dis = 0.0

        gcmd.respond_info(
            '[SAFE_MOVE_Z] Moving Z %.3fmm from %.3fmm toward %.3fmm at '
            '%.3fmm/s with Cartographer scan protection' %
            (guarded_target_z - start_z, start_z, guarded_target_z, speed))
        end_z, triggered = self._guarded_move(
            gcmd, toolhead, guarded_target_z, speed)

        if artificial_z and not triggered:
            raise gcmd.error(
                '[SAFE_MOVE_Z] Cartographer did not detect the bed during '
                'the artificial-Z approach; stopped at backup Z=%.3f' %
                (end_z,))
        if triggered and not artificial_z:
            raise gcmd.error(
                '[SAFE_MOVE_Z] Cartographer detected the bed unexpectedly '
                'at Z=%.3f; preparation stopped' % (end_z,))
        if not triggered and abs(end_z - guarded_target_z) > self.COMPLETION_TOLERANCE:
            raise gcmd.error(
                '[SAFE_MOVE_Z] Move stopped at Z=%.3f; expected Z=%.3f' %
                (end_z, guarded_target_z))

        trigger_z = end_z if triggered else None
        if artificial_z and triggered:
            end_z = self._retreat_after_trigger(
                gcmd, toolhead, trigger_z, speed)
            gcmd.respond_info(
                '[SAFE_MOVE_Z] Cartographer stopped the artificial-Z '
                'approach at Z=%.3f; bed retreated %.3fmm to Z=%.3f' %
                (trigger_z, end_z - trigger_z, end_z))

        completed_distance = end_z - start_z
        # This is the stock prtouch_v3 completion contract.  Publishing only
        # after wait_moves() prevents master-server from continuing while the
        # bed is still moving.
        virtual_sdcard.run_dis = completed_distance
        logging.info(
            '[SAFE_MOVE_Z] completed distance=%.6f start_z=%.6f end_z=%.6f '
            'trigger_z=%s cartographer_triggered=%s artificial_z=%s '
            'recorded_z=%s',
            completed_distance, start_z, end_z, trigger_z, triggered,
            artificial_z, recorded_z)
        gcmd.respond_info(
            '[SAFE_MOVE_Z] Completed Z move; run_dis=%.3f%s' %
            (completed_distance,
             ' (Cartographer stop + 10mm retreat)' if triggered else ''))


def load_config(config):
    return K2SafeMoveZ(config)
