#!/usr/bin/env python3

import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
CONFIGFILE = HERE / "configfile.py"
INSTALLER = HERE / "install.sh"


class SaveConfigRestartContractTests(unittest.TestCase):
    def test_save_config_uses_only_stock_restart(self):
        source = CONFIGFILE.read_text(encoding="utf-8")
        self.assertIn("gcode.request_restart('restart')", source)
        self.assertNotIn("gcode.request_restart('firmware_restart')", source)
        self.assertNotIn("subprocess.Popen", source)
        self.assertNotIn("k2_save_config_restart.sh", source)

    def test_installer_removes_stale_runtime_helper(self):
        source = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("k2_save_config_restart.sh", source)
        self.assertIn("rm -f ${HELPER}", source)
        self.assertNotIn("ln -sfn ${SCRIPT_DIR}/k2_save_config_restart.sh", source)


if __name__ == "__main__":
    unittest.main()
