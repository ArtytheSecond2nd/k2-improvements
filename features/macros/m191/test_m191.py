#!/usr/bin/env python3

import re
import unittest
from pathlib import Path


MACRO = Path(__file__).with_name("m191.cfg").read_text(encoding="utf-8")
OVERRIDES = (
    Path(__file__).parents[1] / "overrides" / "overrides.cfg"
).read_text(encoding="utf-8")

DEFAULTS = {
    "bed_assist_enabled": "1",
    "bed_assist_trigger_delta": "3.0",
    "bed_assist_bed_target": "105.0",
    "bed_assist_degrees_above_commanded": "0.0",
    "bed_assist_z_height": "195.0",
    "circulation_fan_speed": "25.0",
    "chamber_fan_margin": "2.0",
    "bed_restore_tolerance": "5.0",
    "chamber_wait_max_delta": "5.0",
}


def macro_defaults(text):
    section = text.split("[gcode_macro _M191_VARS]", 1)[1].split(
        "[gcode_macro", 1
    )[0]
    return dict(
        re.findall(r"^variable_([A-Za-z0-9_]+):\s*([^\s#]+)", section, re.M)
    )


class M191WorkflowTests(unittest.TestCase):
    def test_managed_and_override_defaults_match(self):
        self.assertEqual(macro_defaults(MACRO), DEFAULTS)
        self.assertEqual(macro_defaults(OVERRIDES), DEFAULTS)

    def test_active_heating_boundary_remains_fixed(self):
        self.assertIn("{% set WAIT_FOR_CHAMBER = S > 35.0 %}", MACRO)

    def test_m141_is_not_redefined_as_a_second_macro(self):
        self.assertNotIn("[gcode_macro M141]", MACRO)
        self.assertNotIn("rename_existing", MACRO)

    def test_nonzero_target_restores_configured_chamber_fan_margin(self):
        wait = MACRO.index("{% set WAIT_FOR_CHAMBER = S > 35.0 %}")
        target = MACRO.index(
            "{% set FAN_TARGET = S + CHAMBER_FAN_MARGIN %}",
            wait,
        )
        apply_target = MACRO.index(
            "SET_TEMPERATURE_FAN_TARGET TEMPERATURE_FAN=chamber_fan "
            "TARGET={FAN_TARGET}",
            target,
        )
        self.assertLess(wait, target)
        self.assertLess(target, apply_target)
        self.assertNotIn("0.0 if WAIT_FOR_CHAMBER", MACRO)

    def test_fixed_target_is_used_when_degrees_above_is_zero(self):
        relative = MACRO.index("{% if DEGREES_ABOVE_COMMANDED > 0.0 %}")
        relative_target = MACRO.index(
            "ORIGINAL_BED_TARGET + DEGREES_ABOVE_COMMANDED", relative
        )
        fixed_branch = MACRO.index("{% else %}", relative_target)
        fixed_target = MACRO.index(
            "{% set RAW_BED_ASSIST_TARGET = FIXED_BED_ASSIST_TARGET %}",
            fixed_branch,
        )
        self.assertLess(relative_target, fixed_branch)
        self.assertLess(fixed_branch, fixed_target)

    def test_calculated_assist_target_is_capped_at_120(self):
        self.assertIn(
            "{% set BED_ASSIST_TARGET = [RAW_BED_ASSIST_TARGET, 120.0]|min %}",
            MACRO,
        )
        self.assertIn(
            "[BED_ASSIST_HEATER_UNCAPPED, 120.0]|min",
            MACRO,
        )

    def test_assist_never_lowers_commanded_bed_target(self):
        self.assertIn("[ORIGINAL_BED_TARGET, BED_ASSIST_TARGET]|max", MACRO)
        self.assertIn("{% if BED_TARGET_WILL_BE_RAISED %}", MACRO)

    def test_assist_skips_when_calculated_target_is_not_above_actual_bed(self):
        self.assertIn("BED_ASSIST_TARGET > ACTUAL_BED_TEMP", MACRO)
        self.assertIn("BED_ASSIST_TARGET <= ACTUAL_BED_TEMP", MACRO)

    def test_assist_enable_and_chamber_delta_gate_entire_sequence(self):
        self.assertIn(
            "BED_ASSIST_ENABLED == 1.0 and WAIT_FOR_CHAMBER and "
            "CHAMBER_TEMP < BED_ASSIST_THRESHOLD and "
            "BED_ASSIST_TARGET > ACTUAL_BED_TEMP",
            MACRO,
        )
        assist = MACRO.index("{% if USE_BED_ASSIST %}")
        move = MACRO.index("G1 Z{BED_ASSIST_Z_HEIGHT} F600", assist)
        fans = MACRO.index("M106 S{CIRCULATION_FAN_PWM}", move)
        self.assertLess(move, fans)

    def test_z_height_range_is_30_through_330(self):
        self.assertIn(
            "BED_ASSIST_Z_HEIGHT < 30.0 or BED_ASSIST_Z_HEIGHT > 330.0",
            MACRO,
        )

    def test_fan_percentage_is_validated_and_converted_to_pwm(self):
        self.assertIn(
            "CIRCULATION_FAN_PERCENT < 0.0 or CIRCULATION_FAN_PERCENT > 100.0",
            MACRO,
        )
        self.assertIn("(CIRCULATION_FAN_PERCENT * 2.55)|round(0)|int", MACRO)
        self.assertIn("M106 S{CIRCULATION_FAN_PWM}", MACRO)
        self.assertIn("M106 P2 S{CIRCULATION_FAN_PWM}", MACRO)

    def test_configured_chamber_wait_and_bed_restore_tolerances_are_used(self):
        self.assertIn(
            'MINIMUM={S} MAXIMUM={S + CHAMBER_WAIT_MAX_DELTA}', MACRO
        )
        self.assertIn("ORIGINAL_BED_TARGET - BED_RESTORE_TOLERANCE", MACRO)
        self.assertIn(
            "MAXIMUM={ORIGINAL_BED_TARGET + BED_RESTORE_TOLERANCE}", MACRO
        )

    def test_zero_bed_target_does_not_wait_for_unreachable_temperature(self):
        self.assertIn("{% if ORIGINAL_BED_TARGET > 0.0 %}", MACRO)
        self.assertIn(
            "Original bed target was off, skipping bed target wait", MACRO
        )

    def test_s_zero_keeps_emergency_shutdown_behavior(self):
        zero = MACRO.index("{% if S == 0 %}")
        off = MACRO.index("TURN_OFF_HEATERS", zero)
        fan_off = MACRO.index("M107", off)
        settings = MACRO.index('printer["gcode_macro _M191_VARS"]', fan_off)
        self.assertLess(zero, off)
        self.assertLess(off, fan_off)
        self.assertLess(fan_off, settings)

    def test_old_direct_fan2_override_is_removed(self):
        self.assertNotIn("SET_PIN PIN=fan2", MACRO)

    def test_respond_messages_do_not_contain_k2_comment_delimiter(self):
        for line in MACRO.splitlines():
            if "RESPOND MSG=" in line:
                self.assertNotIn(";", line, msg=line)


if __name__ == "__main__":
    unittest.main()
