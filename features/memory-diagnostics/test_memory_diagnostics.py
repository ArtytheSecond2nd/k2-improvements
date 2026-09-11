import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("memory_diagnostics.py")
SPEC = importlib.util.spec_from_file_location("memory_diagnostics", MODULE_PATH)
MEMORY_DIAGNOSTICS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MEMORY_DIAGNOSTICS)


class ParserTests(unittest.TestCase):
    def test_key_values_only_return_requested_integer_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "meminfo"
            path.write_text(
                "MemTotal: 512000 kB\nMemFree: 9000 kB\nIgnored: 7 kB\n",
                encoding="utf-8",
            )
            self.assertEqual(
                MEMORY_DIAGNOSTICS.read_key_values(
                    str(path), ("MemTotal", "MemFree")),
                {"MemTotal": 512000, "MemFree": 9000},
            )

    def test_buddyinfo_preserves_all_orders(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "buddyinfo"
            path.write_text(
                "Node 0, zone Normal 1385 230 0 20 18 1 1 0 0 0 0\n",
                encoding="utf-8",
            )
            self.assertEqual(
                MEMORY_DIAGNOSTICS.read_buddyinfo(str(path)),
                "Normal:1385,230,0,20,18,1,1,0,0,0,0",
            )

    def test_pagetypeinfo_separates_normal_migration_types(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pagetypeinfo"
            path.write_text(
                "Node 0, zone Normal, type Unmovable 1 5 0 0\n"
                "Node 0, zone Normal, type Movable 1273 165 0 0\n"
                "Node 0, zone DMA, type Movable 9 8 7 6\n",
                encoding="utf-8",
            )
            self.assertEqual(
                MEMORY_DIAGNOSTICS.read_pagetypeinfo(str(path)),
                "Unmovable:1,5,0,0;Movable:1273,165,0,0",
            )


if __name__ == "__main__":
    unittest.main()
