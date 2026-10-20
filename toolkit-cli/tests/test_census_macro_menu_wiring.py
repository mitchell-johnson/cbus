"""Census wiring for the committed macro-leaf and menu-option maps."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from research import census


ROOT = Path(__file__).resolve().parents[1]
SURFACE_PATH = ROOT / "docs" / "toolkit-surface.json"
MACRO_MAP_PATH = ROOT / "docs" / "toolkit-macro-leaf-map.json"
MENU_MAP_PATH = ROOT / "docs" / "toolkit-menu-option-map.json"


def committed() -> tuple[dict, dict, dict]:
    surface = json.loads(SURFACE_PATH.read_text(encoding="utf-8"))
    macro = json.loads(MACRO_MAP_PATH.read_text(encoding="utf-8"))
    menu = json.loads(MENU_MAP_PATH.read_text(encoding="utf-8"))
    return surface, macro, menu


class CensusMacroMenuWiringTests(unittest.TestCase):
    def test_committed_maps_cover_census_rosters_in_surface_order(self):
        surface, macro, menu = committed()
        summary = census.validate_macro_menu_maps(surface, macro, menu)
        self.assertEqual(summary, {
            "macro_leaves": 179,
            "macro_mapped": 34,
            "macro_pending": 145,
            "menu_leaves": 22,
            "menu_mapped": 8,
            "menu_pending": 14,
        })
        self.assertEqual(
            surface["counts"]["macro_reference_leaves"], summary["macro_leaves"]
        )
        self.assertEqual(
            census.menu_leaf_roster(surface["main_menu_tree"]),
            [row["leaf_id"] for row in menu["leaves"]],
        )

    def test_menu_leaf_roster_walks_surface_order(self):
        tree = {"topic_id": "root", "children": [
            {"topic_id": "a"},
            {"topic_id": "b", "children": [{"topic_id": "c"}]},
        ]}
        self.assertEqual(census.menu_leaf_roster(tree), ["a", "c"])

    def test_roster_or_count_mismatch_is_rejected(self):
        surface, macro, menu = committed()
        mutated = copy.deepcopy(macro)
        mutated["leaves"].pop()
        with self.assertRaisesRegex(ValueError, "Macro leaf map roster"):
            census.validate_macro_menu_maps(surface, mutated, menu)
        mutated = copy.deepcopy(macro)
        mutated["counts"]["pending"] = 0
        with self.assertRaisesRegex(ValueError, "kind counts"):
            census.validate_macro_menu_maps(surface, mutated, menu)
        mutated = copy.deepcopy(menu)
        mutated["leaves"][0], mutated["leaves"][1] = (
            mutated["leaves"][1], mutated["leaves"][0]
        )
        with self.assertRaisesRegex(ValueError, "Menu option map roster"):
            census.validate_macro_menu_maps(surface, macro, mutated)
        mutated = copy.deepcopy(menu)
        mutated["counts"]["mapped"] = 0
        with self.assertRaisesRegex(ValueError, "status counts"):
            census.validate_macro_menu_maps(surface, macro, mutated)


if __name__ == "__main__":
    unittest.main()
