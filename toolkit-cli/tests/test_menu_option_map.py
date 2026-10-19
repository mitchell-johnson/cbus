"""Menu-option map: roster, capability binding, determinism and explicit gaps."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from research import map_menu_options as menu_map


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "docs" / "toolkit-menu-option-map.json"


def committed() -> dict:
    return json.loads(MAP_PATH.read_text(encoding="utf-8"))


def surface_tree() -> dict:
    surface = json.loads((ROOT / "docs/toolkit-surface.json").read_text(encoding="utf-8"))
    return surface["main_menu_tree"]


class MenuOptionMapTests(unittest.TestCase):
    def test_all_22_leaves_are_preserved_in_surface_order(self):
        document = committed()
        ids = [row["leaf_id"] for row in document["leaves"]]
        self.assertEqual(len(ids), 22)
        self.assertEqual(
            ids, [topic_id for topic_id, _ in menu_map.leaf_roster(surface_tree())]
        )
        counts = document["counts"]
        self.assertEqual(counts["leaves"], 22)
        self.assertEqual(counts["mapped"] + counts["pending"], 22)

    def test_every_leaf_resolves_or_names_its_gap(self):
        capabilities = menu_map.live_capabilities()
        for row in committed()["leaves"]:
            with self.subTest(row["leaf_id"]):
                if row["status"] == "mapped":
                    self.assertEqual(row["reasons"], [])
                    self.assertEqual(capabilities.get(row["capability"]), "implemented")
                else:
                    self.assertEqual(row["status"], "pending")
                    self.assertTrue(row["reasons"])
                    for reason in row["reasons"]:
                        self.assertEqual(reason["detail"], menu_map.REASONS[reason["code"]])

    def test_offline_rebuild_is_deterministic_and_byte_identical(self):
        document = committed()
        first = menu_map.render(
            menu_map.build_document(surface_tree(), menu_map.live_capabilities())
        )
        second = menu_map.render(
            menu_map.build_document(surface_tree(), menu_map.live_capabilities())
        )
        self.assertEqual(first, second)
        self.assertEqual(first, MAP_PATH.read_text(encoding="utf-8"))

    def test_tampered_or_missing_input_digests_are_rejected(self):
        for name in ("surface", "capabilities"):
            with self.subTest(name):
                document = copy.deepcopy(committed())
                document["inputs"][name]["sha256"] = "0" * 64
                with self.assertRaisesRegex(ValueError, f"input changed: {name}"):
                    menu_map.validate_document(document)

    def test_pending_rows_require_an_explicit_known_reason(self):
        unresolved = next(
            index
            for index, row in enumerate(committed()["leaves"])
            if row["status"] == "pending"
        )
        cases = {
            "empty reasons": lambda row: row.update(reasons=[]),
            "unknown code": lambda row: row.update(
                reasons=[{"code": "looks_fine", "detail": "x", "subjects": ["y"]}]
            ),
            "altered detail": lambda row: row["reasons"][0].update(detail="x"),
            "extra reason field": lambda row: row["reasons"][0].update(note="x"),
            "claimed mapping": lambda row: row.update(status="mapped"),
            "unknown status": lambda row: row.update(status="partial"),
        }
        for label, mutate in cases.items():
            with self.subTest(label):
                document = committed()
                mutate(document["leaves"][unresolved])
                with self.assertRaises(ValueError):
                    menu_map.validate_document(document)


if __name__ == "__main__":
    unittest.main()
