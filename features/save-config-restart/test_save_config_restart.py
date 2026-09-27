#!/usr/bin/env python3

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


HERE = Path(__file__).resolve().parent
CONFIGFILE = HERE / "configfile.py"
HELPER = HERE / "k2_save_config_restart.sh"
INSTALLER = HERE / "install.sh"


def load_configfile_module():
    spec = importlib.util.spec_from_file_location("managed_configfile", CONFIGFILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SaveConfigRestartContractTests(unittest.TestCase):
    def test_stock_restart_is_preserved_and_helper_is_armed_first(self):
        source = CONFIGFILE.read_text(encoding="utf-8")
        launch = source.index("subprocess.Popen([helper]")
        restart = source.index("gcode.request_restart('restart')")
        self.assertLess(launch, restart)
        self.assertNotIn("gcode.request_restart('firmware_restart')", source)

    def test_helper_handles_ready_fault_and_timeout_before_one_restart(self):
        source = HELPER.read_text(encoding="utf-8")
        self.assertIn("motors-ready", source)
        self.assertIn("startup-fault", source)
        self.assertIn("OUTCOME=timeout", source)
        self.assertIn("K2_FIRMWARE_RESTART_ATTEMPTS=1", source)
        self.assertIn("K2_WAIT_FOR_KLIPPY_STARTUP=0", source)
        self.assertIn("scripts/firmware_restart.sh", source)

    def test_installer_links_runtime_helper(self):
        source = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("k2_save_config_restart.sh", source)
        self.assertIn("ln -sfn ${SCRIPT_DIR}/k2_save_config_restart.sh", source)

    def test_status_build_notifies_compatibility_extras(self):
        source = CONFIGFILE.read_text(encoding="utf-8")
        settings = source.index("self.status_settings = {}")
        notification = source.index(
            'self.printer.send_event("configfile:status_built", self)'
        )
        self.assertLess(settings, notification)

    def test_cxsave_skips_unchanged_files_and_clears_pending_status(self):
        source = CONFIGFILE.read_text(encoding="utf-8")
        cxsave = source.index("def cmd_CXSAVE_CONFIG")
        unchanged = source.index("if data == current_data", cxsave)
        clear = source.index("self._clear_save_pending()", unchanged)
        early_return = source.index("return", clear)
        write = source.index("f.write(data)", cxsave)
        committed_clear = source.index("self._clear_save_pending()", write)
        self.assertLess(unchanged, clear)
        self.assertLess(clear, early_return)
        self.assertLess(early_return, write)
        self.assertLess(write, committed_clear)

    def test_unchanged_cxsave_creates_no_backup_and_clears_pending(self):
        module = load_configfile_module()

        class FakeGCode:
            @staticmethod
            def error(message):
                return RuntimeError(message)

        class FakePrinter:
            def __init__(self, filename):
                self.filename = filename
                self.gcode = FakeGCode()

            def get_start_args(self):
                return {"config_file": self.filename}

            def lookup_object(self, name):
                self_test.assertEqual(name, "gcode")
                return self.gcode

        self_test = self
        with tempfile.TemporaryDirectory() as tempdir:
            primary = Path(tempdir) / "printer.cfg"
            fileconfig = module.configparser.RawConfigParser()
            fileconfig.add_section("auto_addr")
            fileconfig.set(
                "auto_addr",
                "mb_addr_table_uniids",
                "\n  0x27, 0x3E\n  0x00\n  0x00\n  0x00",
            )
            config = module.PrinterConfig.__new__(module.PrinterConfig)
            config.printer = FakePrinter(str(primary))
            config.autosave = SimpleNamespace(fileconfig=fileconfig)
            config.status_save_pending = {
                "auto_addr": {"mb_addr_table_uniids": "same"}
            }
            config.save_config_pending = True
            # The printer runtime uses an older Python whose ConfigParser still
            # provides readfp(). These paths are not material to this focused
            # write/no-write contract test.
            config._build_config_wrapper = lambda _data, _name: None
            config._disallow_include_conflicts = lambda *_args: None

            serialized = config._build_config_string(config.autosave)
            lines = [
                ("#*# " + line).strip() for line in serialized.split("\n")
            ]
            lines.insert(0, "\n" + module.AUTOSAVE_HEADER.rstrip())
            lines.append("")
            primary.write_text("\n".join(lines), encoding="utf-8")
            before = primary.read_text(encoding="utf-8")

            config.cmd_CXSAVE_CONFIG(None)

            self.assertEqual(primary.read_text(encoding="utf-8"), before)
            self.assertEqual(list(Path(tempdir).glob("printer-*.cfg")), [])
            self.assertEqual(config.status_save_pending, {})
            self.assertFalse(config.save_config_pending)

    def test_prunes_only_exact_timestamped_primary_backups_to_five(self):
        module = load_configfile_module()
        config = module.PrinterConfig.__new__(module.PrinterConfig)
        with tempfile.TemporaryDirectory() as tempdir:
            directory = Path(tempdir)
            primary = directory / "printer.cfg"
            primary.write_text("current", encoding="utf-8")
            backups = []
            for second in range(7):
                backup = directory / (
                    "printer-20260927_1200%02d.cfg" % second
                )
                backup.write_text(str(second), encoding="utf-8")
                backups.append(backup)
            unrelated = directory / "printer-personal.cfg"
            unrelated.write_text("keep", encoding="utf-8")
            included = directory / "start_print-20260927_120000.cfg"
            included.write_text("keep", encoding="utf-8")

            config._prune_primary_config_backups(str(primary))

            self.assertEqual(
                [path.name for path in backups if path.exists()],
                [path.name for path in backups[-5:]],
            )
            self.assertTrue(unrelated.exists())
            self.assertTrue(included.exists())

    def test_clear_pending_marks_completed_cxsave_clean(self):
        module = load_configfile_module()
        config = module.PrinterConfig.__new__(module.PrinterConfig)
        config.status_save_pending = {"auto_addr": {"id": "same"}}
        config.save_config_pending = True
        config._clear_save_pending()
        self.assertEqual(config.status_save_pending, {})
        self.assertFalse(config.save_config_pending)

    def test_installer_cleans_historical_backups_beyond_five(self):
        source = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("printer-????????_??????.cfg", source)
        self.assertIn("printer-[0-9]{8}_[0-9]{6}", source)
        self.assertIn("awk 'NR > 5'", source)


if __name__ == "__main__":
    unittest.main()
