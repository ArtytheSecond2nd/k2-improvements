"""Local-only ATC removal regressions. No printer or network access."""

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("axis_twist_removal", HERE / "remove_axis_twist.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class RemovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="k2-atc-removal-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cfg, self.klipper = self.root / "config", self.root / "klipper"
        self.custom, self.extras = self.cfg / "custom", self.klipper / "klippy/extras"
        self.custom.mkdir(parents=True)
        self.extras.mkdir(parents=True)
        self.wrapper = b"local test wrapper; never a real MCU library"
        self.md5 = hashlib.md5(self.wrapper).hexdigest()
        self.entry = M.WRAPPERS["d020e2a1db363c46f4ace6a9aa8c82b5"]
        self.mapping = mock.patch.dict(M.WRAPPERS, {self.md5: (self.entry[0], M.sha(self.wrapper), self.entry[2])})
        self.mapping.start()
        self.addCleanup(self.mapping.stop)
        (self.extras / "prtouch_v3_wrapper.cpython-39.so").write_bytes(self.wrapper)
        self.helper = b"# test retired ATC helper\nself.use_offsets = True\n"
        self.hashes = mock.patch.object(M, "ATC_PROBES", M.ATC_PROBES | {M.sha(self.helper)})
        self.hashes.start()
        self.addCleanup(self.hashes.stop)
        (self.extras / "probe.py").write_bytes(self.helper)
        native = (M.STOCK / "prtouch_v3.py").read_text(encoding="utf-8")
        (self.extras / "prtouch_v3.py").write_text(native.replace(M.NATIVE_NAME, M.PATCHED_NAME), encoding="utf-8")
        (self.extras / "axis_twist_compensation.py").write_text("# retired module\n")
        (self.custom / "axis_twist_compensation.cfg").write_text("[axis_twist_compensation]\nspeed: 200\n")
        (self.custom / "overrides.cfg").write_text("[gcode_macro _START_PRINT_VARS]\nvariable_offset_petg: 0\n")
        (self.custom / "main.cfg").write_text("# main\n[include axis_twist_compensation.cfg]\n[include overrides.cfg]\n")
        self.printer = ("[prtouch_v3]\nz_offset: 0\n[include custom/main.cfg]\n"
                        "#*# [axis_twist_compensation]\n#*# z_compensations = 0.1, -0.1\n"
                        "#*# zy_compensations = 0.2, -0.2\n"
                        "#*# [bed_mesh high_temp_70.0c_30.0c]\n#*# points = 0, 0, 0\n")
        (self.cfg / "printer.cfg").write_text(self.printer)
        self.offset_json = b'{"offsets":{"high_temp":-0.09},"version":1}\n'
        (self.custom / "prtouch_global_z.json").write_bytes(self.offset_json)

    def plan(self):
        return M.plan_removal(self.cfg, self.klipper)

    def ready(self, **overrides):
        status = {"webhooks": {"state": "ready"}, "print_stats": {"state": "standby"},
                  "idle_timeout": {"state": "Ready"}, "configfile": {"save_config_pending": False}}
        status.update(overrides)
        return io.BytesIO(json.dumps({"result": {"status": status}}).encode())

    def argv(self, action):
        return [action, "--config-dir", str(self.cfg), "--klipper-dir", str(self.klipper)]

    def test_all_three_ota_sources_are_integrity_verified_and_keep_stock_correction(self):
        self.assertEqual(len(M.WRAPPERS), 4)  # three shipped identities plus this fixture
        for digest, (version, wrapper_sha, probe_sha) in M.WRAPPERS.items():
            if digest == self.md5:
                continue
            source = M.canonical((M.STOCK / version / "probe.py").read_bytes())
            self.assertEqual(M.sha(source), probe_sha)
            self.assertEqual(len(wrapper_sha), 64)
            self.assertIn(b"get_z_compensation_value(pos)", source)
            self.assertEqual(b"ZMAX_DIST" in source, version != "1.1.3.13")
            self.assertEqual(b"gcode.check_cancel_running()" in source, version == "1.1.5.5")
        self.assertEqual(M.sha(M.canonical((M.STOCK / "prtouch_v3.py").read_bytes())), M.PRTOUCH_SHA)

    def test_wrapper_selects_every_stock_variant_not_firmware_version(self):
        for version, unused, probe_sha in list(M.WRAPPERS.values())[:3]:
            with mock.patch.dict(M.WRAPPERS, {self.md5: (version, M.sha(self.wrapper), probe_sha)}):
                plan = self.plan()
                self.assertEqual(plan["version"], version)
                self.assertEqual(plan["replacements"][self.extras / "probe.py"], (M.STOCK / version / "probe.py").read_bytes())

    def test_native_removal_preserves_mesh_global_material_and_backups(self):
        plan = self.plan()
        backup = M.apply_plan(plan)
        self.assertFalse(plan["cartographer"])
        self.assertEqual((self.extras / "probe.py").read_bytes(), (M.STOCK / "1.1.5.5/probe.py").read_bytes())
        self.assertFalse((self.extras / "axis_twist_compensation.py").exists())
        self.assertFalse((self.custom / "axis_twist_compensation.cfg").exists())
        text = (self.cfg / "printer.cfg").read_text()
        self.assertNotIn("axis_twist_compensation", text)
        self.assertIn("#*# [bed_mesh high_temp_70.0c_30.0c]\n#*# points = 0, 0, 0", text)
        self.assertIn("z_offset: 0", text)
        self.assertEqual((self.custom / "prtouch_global_z.json").read_bytes(), self.offset_json)
        self.assertIn("variable_offset_petg: 0", (self.custom / "overrides.cfg").read_text())
        self.assertEqual((self.custom / "main.cfg").read_text(), "# main\n[include overrides.cfg]\n")
        manifest = json.loads((backup / "manifest.json").read_text())
        printer_record = next(item for item in manifest["files"] if item["path"] == str(self.cfg / "printer.cfg"))
        self.assertEqual((backup / printer_record["backup"]).read_text(), self.printer)

    def test_cartographer_restores_xy_offsets_and_clears_auto_calibration(self):
        (self.custom / "cartographer.cfg").write_text("[cartographer]\nx_offset: 0\ny_offset: 15\n")
        with (self.custom / "main.cfg").open("a") as handle:
            handle.write("[include cartographer.cfg]\n")
        plan = self.plan()
        self.assertTrue(plan["cartographer"])
        M.apply_plan(plan)
        source = (self.extras / "probe.py").read_bytes()
        self.assertEqual(source.count(b"self.use_offsets = True"), 1)
        self.assertNotIn(b"self.use_offsets = False", source)
        self.assertIn("[include cartographer.cfg]", (self.custom / "main.cfg").read_text())
        self.assertNotIn("zy_compensations", (self.cfg / "printer.cfg").read_text())
        self.assertIn("get_z_compensation_value(pos)", source.decode())

    def test_backup_prtouch_is_preferred_and_preserves_original_newlines(self):
        original = (M.STOCK / "prtouch_v3.py").read_bytes().replace(b"\n", b"\r\n")
        (self.extras / "prtouch_v3.py.k2-axis-twist.bak").write_bytes(original)
        M.apply_plan(self.plan())
        self.assertEqual((self.extras / "prtouch_v3.py").read_bytes(), original)

    def test_legacy_removed_registration_is_restored_without_backup(self):
        native = (M.STOCK / "prtouch_v3.py").read_text()
        registration = "    config.get_printer().add_object(" + M.NATIVE_NAME + ")"
        (self.extras / "prtouch_v3.py").write_text(native.replace(registration, M.LEGACY_COMMENT))
        M.apply_plan(self.plan())
        self.assertEqual((self.extras / "prtouch_v3.py").read_bytes(), (M.STOCK / "prtouch_v3.py").read_bytes())

    def test_unknown_wrapper_refuses_all_mutation(self):
        (self.extras / "prtouch_v3_wrapper.cpython-39.so").write_bytes(b"unknown")
        with self.assertRaisesRegex(ValueError, "Reflash"):
            self.plan()
        self.assertEqual((self.cfg / "printer.cfg").read_text(), self.printer)
        self.assertEqual((self.extras / "probe.py").read_bytes(), self.helper)
        self.assertFalse((self.cfg / "atc-removal-backups").exists())

    def test_wrapper_sha_mismatch_refuses_even_when_md5_mapping_exists(self):
        with mock.patch.dict(M.WRAPPERS, {self.md5: (self.entry[0], "0" * 64, self.entry[2])}):
            with self.assertRaisesRegex(ValueError, "Unknown PR Touch"):
                self.plan()

    def test_unknown_probe_refuses(self):
        (self.extras / "probe.py").write_bytes(b"# operator modifications\n")
        with self.assertRaisesRegex(ValueError, "Unrecognized probe"):
            self.plan()

    def test_unrecognized_native_registration_or_backup_refuses(self):
        path = self.extras / "prtouch_v3.py"
        with path.open("a") as handle:
            handle.write("# unexpected change\n")
        with self.assertRaisesRegex(ValueError, "Unrecognized prtouch"):
            self.plan()
        path.write_bytes((M.STOCK / "prtouch_v3.py").read_bytes())
        (self.extras / "prtouch_v3.py.k2-axis-twist.bak").write_text("unknown backup\n")
        with self.assertRaisesRegex(ValueError, "backup is not"):
            self.plan()

    def test_active_sections_and_multiple_saved_sections_are_removed(self):
        text = ("# preserve\r\n[axis_twist_compensation]\r\nz_compensations: .1, .2\r\n"
                "[printer]\r\nmax_velocity: 800\r\n#*# [axis_twist_compensation]\r\n"
                "#*# zy_compensations = .2, .3\r\n#*# [prtouch_v3]\r\n#*# z_offset = 0\r\n")
        cleaned = M.clean_config(text)
        self.assertEqual(cleaned, "# preserve\r\n[printer]\r\nmax_velocity: 800\r\n#*# [prtouch_v3]\r\n#*# z_offset = 0\r\n")

    def test_commented_absolute_and_relative_includes_removed_but_wildcards_retained(self):
        atc = self.custom / "axis_twist_compensation.cfg"
        source = "#[include axis_twist_compensation.cfg]\n[include ../custom/axis_twist_compensation.cfg]\n[include %s]\n[include *.cfg]\n" % atc.as_posix()
        self.assertEqual(M.clean_includes(source, self.custom / "main.cfg", atc), "[include *.cfg]\n")

    def test_saved_values_in_an_included_config_are_removed_not_other_variables(self):
        path = self.custom / "overrides.cfg"
        with path.open("a") as handle:
            handle.write("[axis_twist_compensation]\nz_compensations: .1, .2\n[other]\nkeep: yes\n")
        M.apply_plan(self.plan())
        self.assertEqual(path.read_text(), "[gcode_macro _START_PRINT_VARS]\nvariable_offset_petg: 0\n[other]\nkeep: yes\n")

    def test_missing_or_external_includes_refuse_before_mutation(self):
        for name in ("missing.cfg", "../../outside.cfg"):
            (self.custom / "main.cfg").write_text("[include %s]\n" % name)
            with self.assertRaises(ValueError):
                self.plan()

    def test_native_bytecode_removed_once_then_recreated_stock_cache_is_not_atc(self):
        cache = self.extras / "__pycache__"
        cache.mkdir()
        for name in ("probe.cpython-39.pyc", "prtouch_v3.cpython-39.pyc", "axis_twist_compensation.cpython-39.pyc", "other.cpython-39.pyc"):
            (cache / name).write_bytes(b"compiled fixture")
        M.apply_plan(self.plan())
        self.assertEqual([p.name for p in cache.iterdir()], ["other.cpython-39.pyc"])
        (cache / "probe.cpython-39.pyc").write_bytes(b"fresh stock cache")
        self.assertFalse(M.legacy_present(self.cfg, self.klipper))
        self.assertEqual(M.main(self.argv("--verify-only")), 0)

    def test_file_changed_after_preflight_refuses_without_overwrite(self):
        plan = self.plan()
        (self.custom / "main.cfg").write_text("# user edit\n")
        with self.assertRaisesRegex(ValueError, "changed since preflight"):
            M.apply_plan(plan)
        self.assertEqual((self.custom / "main.cfg").read_text(), "# user edit\n")
        self.assertEqual((self.extras / "probe.py").read_bytes(), self.helper)

    def test_write_failure_rolls_back_earlier_edits_and_retains_backup(self):
        original_write = M.atomic_write
        calls = []
        def fail_once(path, data, mode=0o644):
            calls.append(path)
            if len(calls) == 2:
                raise OSError("simulated write failure")
            return original_write(path, data, mode)
        with mock.patch.object(M, "atomic_write", side_effect=fail_once):
            with self.assertRaisesRegex(RuntimeError, "rollback completed"):
                M.apply_plan(self.plan())
        self.assertEqual((self.extras / "probe.py").read_bytes(), self.helper)
        self.assertEqual((self.cfg / "printer.cfg").read_text(), self.printer)
        self.assertTrue(list((self.cfg / "atc-removal-backups").glob("*/manifest.json")))

    def test_second_idle_check_blocks_a_job_started_during_backup(self):
        def printing():
            raise ValueError("printer started a job")
        with self.assertRaisesRegex(ValueError, "started a job"):
            M.apply_plan(self.plan(), before_commit=printing)
        self.assertEqual((self.extras / "probe.py").read_bytes(), self.helper)

    def test_read_only_preflight_does_not_create_backup_or_change_files(self):
        with mock.patch.object(M.urllib.request, "urlopen", return_value=self.ready()) as url:
            self.assertEqual(M.main(self.argv("--check-only")), 0)
        self.assertIn("/printer/objects/query?", url.call_args.args[0])
        self.assertFalse((self.cfg / "atc-removal-backups").exists())
        self.assertEqual((self.extras / "probe.py").read_bytes(), self.helper)

    def test_apply_requires_two_ready_idle_checks_then_becomes_noop(self):
        with mock.patch.object(M.urllib.request, "urlopen", side_effect=lambda *a, **k: self.ready()) as url:
            self.assertEqual(M.main(self.argv("--apply")), 0)
            self.assertEqual(url.call_count, 2)
        self.assertEqual(M.main(self.argv("--verify-only")), 0)
        with mock.patch.object(M.urllib.request, "urlopen", return_value=self.ready()):
            self.assertEqual(M.main(self.argv("--apply")), 3)
        self.assertEqual(len(list((self.cfg / "atc-removal-backups").iterdir())), 1)

    def test_printing_paused_pending_config_and_not_ready_are_refused(self):
        for overrides in ({"print_stats": {"state": "printing"}}, {"print_stats": {"state": "paused"}},
                          {"idle_timeout": {"state": "Printing"}}, {"configfile": {"save_config_pending": True}},
                          {"configfile": {}}, {"webhooks": {"state": "shutdown"}}):
            with self.subTest(overrides=overrides):
                with mock.patch.object(M.urllib.request, "urlopen", return_value=self.ready(**overrides)):
                    self.assertEqual(M.main(self.argv("--apply")), 1)
                self.assertEqual((self.extras / "probe.py").read_bytes(), self.helper)

    def test_disconnected_moonraker_is_refused(self):
        with mock.patch.object(M.urllib.request, "urlopen", side_effect=OSError("unavailable")):
            self.assertEqual(M.main(self.argv("--apply")), 1)
        self.assertFalse((self.cfg / "atc-removal-backups").exists())

    def symlink(self, link, target):
        if M.exists(link):
            link.unlink()
        try:
            link.symlink_to(target)
        except OSError as error:
            self.skipTest("symlink creation unavailable: %s" % error)

    def test_probe_link_is_replaced_without_editing_repository_target(self):
        source = self.root / "repository/features/axis_twist_compensation/probe.py"
        source.parent.mkdir(parents=True)
        source.write_bytes(self.helper)
        self.symlink(self.extras / "probe.py", source)
        M.apply_plan(self.plan())
        self.assertEqual(source.read_bytes(), self.helper)
        self.assertFalse((self.extras / "probe.py").is_symlink())

    def test_dangling_retired_probe_link_after_pull_is_recoverable(self):
        target = self.root / "deleted/features/axis_twist_compensation/probe.py"
        self.symlink(self.extras / "probe.py", target)
        self.assertTrue(M.legacy_present(self.cfg, self.klipper))
        backup = M.apply_plan(self.plan())
        self.assertFalse((self.extras / "probe.py").is_symlink())
        record = next(item for item in json.loads((backup / "manifest.json").read_text())["files"]
                      if item["path"] == str(self.extras / "probe.py"))
        self.assertEqual(record["link"], str(target))

    def test_config_symlink_outside_root_is_refused(self):
        outside = self.root / "outside.cfg"
        outside.write_text("[axis_twist_compensation]\nz_compensations: .1, .2\n")
        self.symlink(self.custom / "overrides.cfg", outside)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.plan()

    def test_dangling_link_branch_with_virtual_link_on_windows(self):
        # Windows CI often lacks native symlink privileges. Exercise the same
        # Linux link branch with a virtual dangling link in addition to the
        # real-filesystem test above, which runs when symlinks are available.
        path = self.extras / "probe.py"
        target = str(self.root / "deleted/features/axis_twist_compensation/probe.py")
        real_exists, real_symlink = Path.exists, Path.is_symlink
        with mock.patch.object(Path, "is_symlink", lambda p: True if p == path else real_symlink(p)), \
             mock.patch.object(Path, "exists", lambda p: False if p == path else real_exists(p)), \
             mock.patch.object(M.os, "readlink", return_value=target):
            plan = self.plan()
            self.assertIn(path, plan["replacements"])
            self.assertEqual(plan["expected"][path]["link"], target)
            self.assertIsNone(plan["expected"][path]["data"])

    def test_symlinked_cache_is_refused_before_any_cleanup(self):
        cache = self.extras / "__pycache__"
        real_symlink = Path.is_symlink
        with mock.patch.object(Path, "is_symlink", lambda p: True if p == cache else real_symlink(p)):
            with self.assertRaisesRegex(ValueError, "cache directory"):
                self.plan()

    def test_invalid_bundled_source_is_refused(self):
        with mock.patch.dict(M.WRAPPERS, {self.md5: (self.entry[0], M.sha(self.wrapper), "0" * 64)}):
            with self.assertRaisesRegex(ValueError, "integrity verification"):
                self.plan()

    def test_config_mutated_during_backup_is_not_overwritten(self):
        plan = self.plan()
        original_snapshot = M.snapshot
        calls = [0]
        path = self.custom / "main.cfg"
        def change_at_second_snapshot(target):
            if target == path:
                calls[0] += 1
                if calls[0] == 2:
                    path.write_text("# concurrent user edit\n")
            return original_snapshot(target)
        with mock.patch.object(M, "snapshot", side_effect=change_at_second_snapshot):
            with self.assertRaisesRegex(ValueError, "changed during backup"):
                M.apply_plan(plan)
        self.assertEqual(path.read_text(), "# concurrent user edit\n")
        self.assertEqual((self.extras / "probe.py").read_bytes(), self.helper)

    def test_unrelated_managed_config_links_are_read_not_refused_or_edited(self):
        # Same shape as managed START_PRINT/M191 symlinks into the checkout.
        path = self.custom / "overrides.cfg"
        real_symlink = Path.is_symlink
        with mock.patch.object(Path, "is_symlink", lambda p: True if p == path else real_symlink(p)):
            plan = self.plan()
            self.assertNotIn(path, plan["replacements"])

    def test_external_config_needing_atc_cleanup_is_refused(self):
        outside = self.root / "outside.cfg"
        outside.write_text("[axis_twist_compensation]\nz_compensations: .1, .2\n")
        with (self.custom / "main.cfg").open("a") as output:
            output.write("[include %s]\n" % outside.as_posix())
        with self.assertRaisesRegex(ValueError, "outside the config directory"):
            self.plan()

    def test_missing_wrapper_has_explicit_reflash_instruction(self):
        (self.extras / "prtouch_v3_wrapper.cpython-39.so").unlink()
        with self.assertRaisesRegex(ValueError, "Reflash matching stock firmware"):
            self.plan()

    def test_atc_config_with_unrelated_sections_is_not_deleted(self):
        path = self.custom / "axis_twist_compensation.cfg"
        path.write_text("[axis_twist_compensation]\nspeed: 200\n[other]\nkeep: yes\n")
        with self.assertRaisesRegex(ValueError, "contains another section"):
            self.plan()
        self.assertIn("keep: yes", path.read_text())


if __name__ == "__main__":
    unittest.main()
