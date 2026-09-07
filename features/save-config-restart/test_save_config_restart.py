#!/usr/bin/env python3

import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
CONFIGFILE = HERE / "configfile.py"
HELPER = HERE / "k2_save_config_restart.sh"
INSTALLER = HERE / "install.sh"


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


if __name__ == "__main__":
    unittest.main()
