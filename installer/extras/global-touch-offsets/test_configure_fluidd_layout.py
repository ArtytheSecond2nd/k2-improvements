#!/usr/bin/env python3

import copy
import unittest

import configure_fluidd_layout as layout


class FluiddLayoutTests(unittest.TestCase):
    def test_creates_category_and_editor_metadata(self):
        source = {"theme": {"isDark": True}, "macros": {"stored": [], "categories": []}}
        result = layout.merge_layout(source)
        category = result["macros"]["categories"][0]
        item = result["macros"]["stored"][0]

        self.assertEqual(category["name"], "Just Z Offsets")
        self.assertEqual(item["name"], "GLOBAL_Z_OFFSETS_CARTO")
        self.assertEqual(item["alias"], "Global_Z_Offsets_Carto")
        self.assertEqual(item["categoryId"], category["id"])
        self.assertEqual(item["color"], "#2196F3")
        self.assertTrue(item["disabledWhilePrinting"])
        self.assertEqual(result["theme"], source["theme"])

    def test_preserves_user_alias_and_valid_category(self):
        source = {
            "macros": {
                "categories": [{"id": "mine", "name": "My offsets"}],
                "stored": [
                    {
                        "name": "global_z_offsets_carto",
                        "alias": "My editor",
                        "categoryId": "mine",
                        "visible": False,
                    }
                ],
            }
        }
        result = layout.merge_layout(source)
        item = result["macros"]["stored"][0]
        self.assertEqual(item["alias"], "My editor")
        self.assertEqual(item["categoryId"], "mine")
        self.assertFalse(item["visible"])
        self.assertEqual(item["color"], "#2196F3")
        self.assertTrue(item["disabledWhilePrinting"])

    def test_is_idempotent(self):
        first = layout.merge_layout({"macros": {}})
        second = layout.merge_layout(copy.deepcopy(first))
        self.assertEqual(second, first)

    def test_renames_existing_legacy_category(self):
        source = {
            "macros": {
                "categories": [{"id": "legacy", "name": "Global Touch offsets"}],
                "stored": [
                    {
                        "name": "GLOBAL_Z_OFFSETS_CARTO",
                        "categoryId": "legacy",
                    }
                ],
            }
        }
        result = layout.merge_layout(source)
        self.assertEqual(
            result["macros"]["categories"],
            [{"id": "legacy", "name": "Just Z Offsets"}],
        )
        self.assertEqual(result["macros"]["stored"][0]["categoryId"], "legacy")

    def test_rejects_malformed_state(self):
        with self.assertRaises(layout.LayoutError):
            layout.merge_layout({"macros": {"categories": {}, "stored": []}})


if __name__ == "__main__":
    unittest.main()
