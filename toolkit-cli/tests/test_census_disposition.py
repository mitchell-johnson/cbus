"""P0.01 census disposition: every unresolved dialog has evidenced scope.

Each of the 17 unresolved dialogs carries exactly one census disposition:
absent_in_1_18 with executable-absence evidence, or ledger_owned with a named
ledger owner.  No disposition claims an unsupported editor, GUI execution or
hardware acceptance, and stable dialog IDs are preserved.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from research import map_dialog_candidates as dialog_map


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "docs" / "toolkit-dialog-map.json"
SURFACE_PATH = ROOT / "docs" / "toolkit-surface.json"


def committed() -> dict:
    return json.loads(MAP_PATH.read_text(encoding="utf-8"))


class CensusDispositionTests(unittest.TestCase):
    def test_stable_ids_preserved_in_census_order(self):
        document = dialog_map.load_committed()
        surface = json.loads(SURFACE_PATH.read_text(encoding="utf-8"))
        expected = [row["id"] for row in surface["device_dialog_candidates"]]
        self.assertEqual([row["dialog_id"] for row in document["dialogs"]], expected)
        self.assertEqual(len(expected), 118)

    def test_every_unresolved_dialog_has_one_evidenced_disposition(self):
        document = committed()
        unresolved = [row for row in document["dialogs"] if row["status"] == "unresolved"]
        self.assertEqual(len(unresolved), 17)
        self.assertEqual(document["counts"]["with_census_disposition"], 17)
        self.assertEqual(
            document["counts"]["census_disposition"],
            {"absent_in_1_18": 3, "ledger_owned": 14},
        )
        for row in document["dialogs"]:
            with self.subTest(row["dialog_id"]):
                if row["status"] == "resolved":
                    self.assertNotIn("census_disposition", row)
                else:
                    disposition = row["census_disposition"]
                    self.assertIn(disposition["kind"], dialog_map.CENSUS_DISPOSITION_KINDS)
                    self.assertEqual(
                        disposition["note"],
                        dialog_map.CENSUS_DISPOSITION_NOTES[disposition["kind"]],
                    )
                    self.assertTrue(disposition["owner_ledger_id"])
                    self.assertTrue(disposition["subjects"])
                    # Census scope only: never claim GUI or hardware acceptance.
                    self.assertNotIn("accepted", disposition["note"].lower())
                    self.assertIn("Census scope only", disposition["note"])

    def test_absent_dispositions_carry_executable_absence_evidence(self):
        document = committed()
        help_only = document["help_only_unit_types"]
        self.assertEqual(
            sorted(help_only),
            ["KEYH5", "PC_INTU", "WPAD2D1", "WPAD2R1"],
        )
        by_id = {row["dialog_id"]: row for row in document["dialogs"]}
        for dialog_id, absent in (
            ("dialog:19973.htm", ["KEYH5"]),
            ("dialog:10747.htm", ["PC_INTU"]),
            ("dialog:12558.htm", ["WPAD2D1", "WPAD2R1"]),
        ):
            with self.subTest(dialog_id):
                row = by_id[dialog_id]
                disposition = row["census_disposition"]
                self.assertEqual(disposition["kind"], "absent_in_1_18")
                self.assertEqual(disposition["subjects"], absent)
                self.assertEqual(
                    disposition["owner_ledger_id"], row["ledger_ids"][0]
                )
                self.assertEqual(
                    disposition["absence_evidence"],
                    {name: help_only[name] for name in absent},
                )
                for name in absent:
                    self.assertEqual(
                        disposition["absence_evidence"][name],
                        {"utf16_literal": False, "short_string": False},
                    )
                    # Absent subjects are unknown in the committed unit table.
                    self.assertNotIn(name, document["unit_types"])
                # The absent reason subjects match the disposition subjects.
                reason = next(
                    reason for reason in row["unresolved_reasons"]
                    if reason["code"] == "help_unit_type_absent_from_executable"
                )
                self.assertEqual(sorted(reason["subjects"]), absent)
        # Mixed dialog keeps its present subjects pending under the same owner.
        mixed = by_id["dialog:12558.htm"]["census_disposition"]
        self.assertEqual(
            mixed["pending_subjects"],
            ["WRD0D1", "WRD0R1", "WRD1D1", "WRD1R1", "WRD2D1",
             "WRD2R1", "WRD3D1", "WRD3R1", "WRD4D1", "WRD4R1"],
        )
        self.assertEqual(mixed["owner_ledger_id"], "toolkit-differential-acceptance")

    def test_ledger_owned_dispositions_name_an_owner_without_new_editors(self):
        document = committed()
        by_id = {row["dialog_id"]: row for row in document["dialogs"]}
        owned_ids = [
            row["dialog_id"] for row in document["dialogs"]
            if row.get("census_disposition", {}).get("kind") == "ledger_owned"
        ]
        self.assertEqual(len(owned_ids), 14)
        for dialog_id in owned_ids:
            with self.subTest(dialog_id):
                row = by_id[dialog_id]
                disposition = row["census_disposition"]
                self.assertEqual(disposition["owner_ledger_id"], row["ledger_ids"][0])
                self.assertEqual(disposition["owner_ledger_id"], row["triage_ledger_id"])
                reason = next(
                    reason for reason in row["unresolved_reasons"]
                    if reason["code"] == "generic_ledger_only"
                )
                self.assertEqual(disposition["subjects"], sorted(reason["subjects"]))
                self.assertNotIn("absence_evidence", disposition)
                self.assertNotIn("pending_subjects", disposition)
                # P0.01 adds owners without claiming unsupported editors.
                self.assertNotIn("implemented_editors", row)

    def test_absent_subjects_claim_no_unsupported_editors(self):
        document = committed()
        admitted: set[str] = set()
        for editor in dialog_map.IMPLEMENTED_EDITORS:
            admitted.update(dialog_map._editor_unit_types(editor))
        for name in ("KEYH5", "PC_INTU", "WPAD2D1", "WPAD2R1"):
            with self.subTest(name):
                self.assertNotIn(name, admitted)
        # The one unresolved dialog with an editor links only present types.
        row = next(
            row for row in document["dialogs"]
            if row["dialog_id"] == "dialog:19973.htm"
        )
        self.assertEqual(
            row["implemented_editors"][0]["unit_types"],
            ["KEYH1", "KEYH2", "KEYH3", "KEYH4"],
        )

    def test_tampered_disposition_is_rejected(self):
        document = committed()
        unresolved = next(
            row for row in document["dialogs"] if row["status"] == "unresolved"
        )
        cases = {
            "missing disposition": lambda row: row.pop("census_disposition"),
            "unknown kind": lambda row: row["census_disposition"].update(kind="looks_fine"),
            "changed owner": lambda row: row["census_disposition"].update(owner_ledger_id="other"),
            "changed subjects": lambda row: row["census_disposition"].update(subjects=[]),
            "changed note": lambda row: row["census_disposition"].update(note="x"),
            "resolved carries disposition": lambda row: None,
        }
        for label, mutate in cases.items():
            with self.subTest(label):
                mutated = copy.deepcopy(document)
                target = next(
                    row for row in mutated["dialogs"]
                    if row["dialog_id"] == unresolved["dialog_id"]
                )
                if label == "resolved carries disposition":
                    resolved = next(
                        row for row in mutated["dialogs"] if row["status"] == "resolved"
                    )
                    resolved["census_disposition"] = copy.deepcopy(
                        unresolved["census_disposition"]
                    )
                else:
                    mutate(target)
                with self.assertRaises(ValueError):
                    dialog_map.validate_document(mutated)


if __name__ == "__main__":
    unittest.main()
