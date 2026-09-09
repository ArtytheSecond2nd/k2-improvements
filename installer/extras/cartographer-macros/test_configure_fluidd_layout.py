#!/usr/bin/env python3

import copy
import unittest

import configure_fluidd_layout as layout


class FluiddLayoutTests(unittest.TestCase):
    def test_creates_category_and_all_aliases_without_renaming_macros(self):
        source = {
            "theme": {"isDark": True},
            "macros": {
                "stored": [{"name": "OTHER", "alias": "Mine", "visible": False}],
                "categories": [{"id": "other", "name": "Utilities"}],
                "expanded": [0],
            },
        }

        result = layout.merge_layout(source)
        category = next(
            item
            for item in result["macros"]["categories"]
            if item["name"] == layout.CATEGORY_NAME
        )
        targets = {
            item["name"]: item
            for item in result["macros"]["stored"]
            if item["name"].startswith("A")
        }

        self.assertEqual(
            list(targets), [name for name, _alias, _color in layout.MACRO_LAYOUT]
        )
        self.assertEqual(
            [targets[name]["alias"] for name, _alias, _color in layout.MACRO_LAYOUT],
            [alias for _name, alias, _color in layout.MACRO_LAYOUT],
        )
        self.assertEqual(
            [targets[name]["color"] for name, _alias, _color in layout.MACRO_LAYOUT],
            [color for _name, _alias, color in layout.MACRO_LAYOUT],
        )
        self.assertTrue(all(item["categoryId"] == category["id"] for item in targets.values()))
        self.assertEqual(result["macros"]["expanded"], [0])
        self.assertEqual(result["theme"], {"isDark": True})
        self.assertEqual(result["macros"]["stored"][0], source["macros"]["stored"][0])

    def test_reuses_named_category_and_preserves_user_customizations(self):
        source = {
            "macros": {
                "categories": [
                    {"id": "carto-user-id", "name": "Cartographer Calibration"},
                    {"id": "favorites", "name": "Favorites"},
                ],
                "stored": [
                    {
                        "name": "a11_carto_select_default",
                        "alias": "My Default Plate",
                        "categoryId": "favorites",
                        "visible": False,
                        "color": "#123456",
                        "order": 9,
                    },
                    {
                        "name": "A12_CARTO_SELECT_TEXTURED_PEI",
                        "alias": "",
                        "categoryId": "0",
                        "visible": True,
                    },
                ],
            }
        }

        result = layout.merge_layout(source)
        categories = result["macros"]["categories"]
        self.assertEqual(len(categories), 2)
        first = result["macros"]["stored"][0]
        self.assertEqual(first["name"], "a11_carto_select_default")
        self.assertEqual(first["alias"], "My Default Plate")
        self.assertEqual(first["categoryId"], "favorites")
        self.assertFalse(first["visible"])
        self.assertEqual(first["color"], "#123456")
        self.assertEqual(first["order"], 9)
        second = result["macros"]["stored"][1]
        self.assertEqual(second["alias"], "TEXTURED_PEI")
        self.assertEqual(second["color"], "success")
        self.assertEqual(second["categoryId"], "carto-user-id")

    def test_repairs_orphaned_category_assignment(self):
        source = {
            "macros": {
                "categories": [],
                "stored": [
                    {
                        "name": "A63_CARTO_INFO",
                        "alias": "",
                        "categoryId": "deleted-category",
                    }
                ],
            }
        }

        result = layout.merge_layout(source)
        category = result["macros"]["categories"][0]
        item = result["macros"]["stored"][0]
        self.assertEqual(item["categoryId"], category["id"])
        self.assertEqual(item["alias"], "CARTO_INFO")
        self.assertEqual(item["color"], "primary")

    def test_is_idempotent(self):
        first = layout.merge_layout({"macros": {}})
        second = layout.merge_layout(copy.deepcopy(first))
        self.assertEqual(second, first)

    def test_rejects_malformed_fluidd_state(self):
        with self.assertRaises(layout.LayoutError):
            layout.merge_layout({"macros": {"categories": {}, "stored": []}})
        with self.assertRaises(layout.LayoutError):
            layout.merge_layout({"macros": {"categories": [], "stored": {}}})


if __name__ == "__main__":
    unittest.main()
