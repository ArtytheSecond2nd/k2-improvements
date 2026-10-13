#!/usr/bin/env python3
"""Render native START_PRINT/mesh branches without contacting a printer."""

import pathlib
import re
import shlex
import unittest

import jinja2


HERE = pathlib.Path(__file__).resolve().parent
MIGRATION_ID = "prtouch-final-z-after-tilt-v1"


def macro_body(path, name):
    text = path.read_text(encoding="utf-8")
    section = text.split("[gcode_macro %s]" % name, 1)[1]
    section = re.split(r"^\[", section, maxsplit=1, flags=re.MULTILINE)[0]
    return section.split("gcode:", 1)[1]


def context(*, cartographer=False, existing_mesh=False, plate_aware=True):
    printer = {
        "gcode_macro _START_PRINT_VARS": {
            "carto_final_z_mode": "touch", "heat_soak": 0,
            "bed_mesh_soak": 0, "offset_petg": 0, "offset_default": 0,
        },
        "gcode_macro _M191_VARS": {"chamber_fan_margin": 2},
        "toolhead": {"homed_axes": "xyz"},
        "bed_mesh": {"profiles": {}},
        "configfile": {"settings": {"bed_mesh": {
            "adaptive_margin": 0, "mesh_min": [5, 5], "mesh_max": [345, 345],
        }}},
        "k2_prtouch_global_z": {},
        "k2_material_z_offset_editor": {},
    }
    if cartographer:
        printer["cartographer"] = {}
    if plate_aware:
        printer["gcode_macro _PLATE_AWARE_MESH"] = {}
    profile = ("high_temp_" if plate_aware else "") + "70.0c_30.0c"
    if existing_mesh:
        printer["bed_mesh"]["profiles"][profile] = {}
    return {
        "printer": printer,
        "params": {"BED_TEMP": "70", "CHAMBER_TEMP": "30",
                   "EXTRUDER_TEMP": "240", "MATERIAL": "PETG",
                   "SURFACE": "high_temp" if plate_aware else ""},
        "action_raise_error": lambda message: (_ for _ in ()).throw(
            AssertionError(message)),
    }


def render(body, ctx):
    env = jinja2.Environment(variable_start_string="{", variable_end_string="}")
    return [line.split("#", 1)[0].strip()
            for line in env.from_string(body).render(ctx).splitlines()
            if line.split("#", 1)[0].strip()]


def expand_mesh(commands, ctx):
    result = []
    for command in commands:
        parts = shlex.split(command)
        if parts[0] in ("MESH_IF_NEEDED", "_CREATE_MESH"):
            nested = dict(ctx, params=dict(part.split("=", 1) for part in parts[1:]))
            body = macro_body(HERE.parent / "bed_mesh" / "bed_mesh.cfg", parts[0])
            result.extend(expand_mesh(render(body, nested), nested))
        else:
            result.append(command)
    return result


class NativeZReferenceTests(unittest.TestCase):
    def start_commands(self, **options):
        ctx = context(**options)
        return expand_mesh(render(macro_body(HERE / "start_print.cfg", "START_PRINT"),
                                  ctx), ctx)

    def test_saved_and_new_native_meshes_both_finish_with_clean_home(self):
        for plate_aware in (False, True):
            for existing_mesh in (False, True):
                with self.subTest(plate_aware=plate_aware, existing_mesh=existing_mesh):
                    commands = self.start_commands(plate_aware=plate_aware,
                                                   existing_mesh=existing_mesh)
                    home = max(i for i, cmd in enumerate(commands) if cmd == "G28 Z")
                    self.assertEqual(commands[home-2:home+2], [
                        "BOX_NOZZLE_CLEAN", "M109 S140", "G28 Z", "BED_MESH_CLEAR",
                    ])
                    self.assertLess(max(i for i, cmd in enumerate(commands)
                                        if cmd == "Z_TILT_ADJUST"), home)
                    load = next(i for i, cmd in enumerate(commands)
                                if cmd.startswith("BED_MESH_PROFILE LOAD="))
                    apply = next(i for i, cmd in enumerate(commands)
                                 if cmd.startswith("K2_PRTOUCH_GLOBAL_Z_APPLY"))
                    self.assertLess(home, load)
                    self.assertLess(load, apply)
                    self.assertLess(apply, commands.index("M109 S240.0"))
                    self.assertEqual(commands.count("K2_MATERIAL_Z_APPLY MATERIAL=\"PETG\""), 1)
                    calibration = [cmd for cmd in commands
                                   if cmd.startswith("BED_MESH_CALIBRATE")]
                    self.assertEqual(len(calibration), 0 if existing_mesh else 1)
                    profile = ("high_temp_" if plate_aware else "") + "70.0c_30.0c"
                    self.assertIn("BED_MESH_PROFILE LOAD=" + profile, commands)

    def test_native_first_post_soak_home_waits_for_140_and_clears_default(self):
        commands = self.start_commands(existing_mesh=True)
        home = commands.index("G28 Z")
        self.assertEqual(commands[home-1:home+2], [
            'STATUS_MSG PREFIX="[START_PRINT]:" MSG="Rehoming Z after reaching bedtemp/soak"',
            "G28 Z", "BED_MESH_CLEAR",
        ])
        self.assertIn("M109 S140", commands[:home])
        self.assertLess(home, commands.index("Z_TILT_ADJUST"))

    def test_standalone_native_mesh_creation_clears_mesh_before_tilt(self):
        commands = render(macro_body(HERE.parent / "bed_mesh" / "bed_mesh.cfg",
                                     "_CREATE_MESH"), context())
        tilt = commands.index("Z_TILT_ADJUST")
        self.assertEqual(commands[tilt-1:tilt+5], [
            "BED_MESH_CLEAR", "Z_TILT_ADJUST", "BOX_NOZZLE_CLEAN",
            "M109 S140", "G28 Z", "BED_MESH_CLEAR",
        ])
        self.assertLess(tilt + 5, next(i for i, cmd in enumerate(commands)
                                     if cmd.startswith("BED_MESH_CALIBRATE")))

    def test_cartographer_startup_keeps_its_existing_homing_sequence(self):
        for mode in ("touch", "scan"):
            with self.subTest(mode=mode):
                ctx = context(cartographer=True)
                ctx["printer"]["gcode_macro _START_PRINT_VARS"]["carto_final_z_mode"] = mode
                commands = render(macro_body(HERE / "start_print.cfg", "START_PRINT"), ctx)
                home = commands.index("G28 Z")
                self.assertNotIn("M109 S140", commands[:home])
                self.assertEqual(commands.count("G28 Z"), 1)
                self.assertNotIn("BED_MESH_CLEAR", commands)
                self.assertEqual(commands.count("BOX_NOZZLE_CLEAN"), 1)
                final_home = "_CARTOGRAPHER_%s_HOME_WITH_TEMPS" % mode.upper()
                clean = commands.index("BOX_NOZZLE_CLEAN")
                self.assertEqual(commands[clean+1], final_home)
                self.assertFalse(any(cmd.startswith("K2_PRTOUCH_GLOBAL_Z_APPLY")
                                     for cmd in commands))

    def test_cartographer_create_mesh_retains_its_old_order(self):
        commands = render(macro_body(HERE.parent / "bed_mesh" / "bed_mesh.cfg",
                                     "_CREATE_MESH"), context(cartographer=True))
        tilt = commands.index("Z_TILT_ADJUST")
        self.assertEqual(commands[tilt:tilt+3], [
            "Z_TILT_ADJUST", "G28 Z", "BOX_NOZZLE_CLEAN",
        ])
        self.assertNotIn("BED_MESH_CLEAR", commands)

    def test_fix_has_one_macros_migration_independent_of_atc(self):
        catalog = (HERE.parents[2] / "installer" / "migrations" / "catalog.sh").read_text(
            encoding="utf-8")
        entries = [line for line in catalog.splitlines()
                   if line.startswith(MIGRATION_ID + "|")]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].split("|", 3)[1:3], ["macros", "is_macros"])
        self.assertIn("recheck plate Z offsets", entries[0])


if __name__ == "__main__":
    unittest.main()
