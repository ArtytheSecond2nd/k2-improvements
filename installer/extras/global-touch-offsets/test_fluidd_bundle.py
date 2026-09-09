#!/usr/bin/env python3

import json
import re
import unittest
import zipfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "fluidd-v1.37.4.zip"
SOURCE_PATCH = HERE / "fluidd-v1.37.4.patch"
INSTALLER = HERE / "install.sh"


class FluiddBundleTests(unittest.TestCase):
    def test_bundle_contains_matching_jacob_release_metadata(self):
        with zipfile.ZipFile(ARCHIVE) as bundle:
            self.assertEqual(bundle.read(".version").decode(), "v1.37.4")
            release = json.loads(bundle.read("release_info.json"))
            self.assertEqual(release["project_owner"], "Jacob10383")
            self.assertEqual(release["version"], "v1.37.4")
            self.assertEqual(bundle.read("global-touch-offsets-support.txt"), b"1\n")
            brands = json.loads(bundle.read("config.json"))["themePresets"]
            brand_names = {brand["name"] for brand in brands}
            self.assertIn("Automated Layers", brand_names)
            self.assertIn("Snapmaker", brand_names)

    def test_bundle_index_and_service_worker_reference_existing_assets(self):
        with zipfile.ZipFile(ARCHIVE) as bundle:
            names = set(bundle.namelist())
            index = bundle.read("index.html").decode("utf-8")
            self.assertIn("sw.js", names)
            for asset in re.findall(r'\./(assets/[^" ]+)', index):
                self.assertIn(asset, names)

    def test_bundle_contains_live_dialog_protocol(self):
        with zipfile.ZipFile(ARCHIVE) as bundle:
            scripts = [
                bundle.read(name)
                for name in bundle.namelist()
                if name.startswith("assets/") and name.endswith(".js")
            ]
            for token in (
                b"global_touch_offsets_",
                b"K2_CARTOGRAPHER_GLOBAL_Z_STAGE",
                b"Bed down / farther",
                b"webrtc-crealityk2rtc",
            ):
                self.assertTrue(
                    any(token in script for script in scripts),
                    "missing bundled UI token: {!r}".format(token),
                )

    def test_source_patch_and_installer_are_self_contained(self):
        patch = SOURCE_PATCH.read_text(encoding="utf-8")
        installer = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("GlobalTouchOffsetsDialog.vue", patch)
        self.assertIn("global-touch-offsets-support.txt", patch)
        self.assertIn("fluidd-v1.37.4.zip", installer)
        self.assertNotIn("Rcpilot33/fluidd", installer)


if __name__ == "__main__":
    unittest.main()
