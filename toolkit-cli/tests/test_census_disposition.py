"""Census dispositions for unresolved device dialogs (#13 P0.01, #38 P5.01)."""
from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest import mock

from research import map_dialog_candidates as dialog_map


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "docs" / "toolkit-dialog-map.json"
LEDGER_PATH = ROOT / "src" / "cbus_toolkit" / "capabilities.json"
REGISTER_PATH = ROOT / "src" / "cbus_toolkit" / "parity-obligations.json"
SURFACE_PATH = ROOT / "docs" / "toolkit-surface.json"
ABSENT_IN_1_18 = {"dialog:10747.htm", "dialog:12558.htm", "dialog:19973.htm"}


def committed() -> dict:
    return json.loads(MAP_PATH.read_text(encoding="utf-8"))


def ledger() -> dict:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


class CensusDispositionTests(unittest.TestCase):
    def test_stable_ids_preserved_in_census_order(self):
        document = dialog_map.load_committed()
        surface = json.loads(SURFACE_PATH.read_text(encoding="utf-8"))
        expected = [row["id"] for row in surface["device_dialog_candidates"]]
        self.assertEqual([row["dialog_id"] for row in document["dialogs"]], expected)
        self.assertEqual(len(expected), 118)

    def test_every_unresolved_dialog_has_a_disposition(self):
        document = dialog_map.load_committed()
        self.assertEqual(document["census_disposition_codes"], dialog_map.CENSUS_DISPOSITIONS)
        self.assertEqual(
            document["counts"]["census_dispositions"], {"absent_in_1_18": 3, "ledger_owned": 14}
        )
        for row in document["dialogs"]:
            with self.subTest(row["dialog_id"]):
                if row["status"] == "resolved":
                    self.assertNotIn("census_disposition", row)
                    continue
                disposition = row["census_disposition"]
                self.assertIn(disposition["code"], dialog_map.CENSUS_DISPOSITIONS)
                self.assertEqual(
                    [entry["reason"] for entry in disposition["reasons"]],
                    [reason["code"] for reason in row["unresolved_reasons"]],
                )
                self.assertEqual(
                    disposition["code"] == "absent_in_1_18", row["dialog_id"] in ABSENT_IN_1_18
                )
                for entry, reason in zip(disposition["reasons"], row["unresolved_reasons"]):
                    self.assertEqual(entry["subjects"], reason["subjects"])
                    self.assertEqual(
                        entry["disposition"], dialog_map.DISPOSITION_BY_REASON[reason["code"]]
                    )

    def test_absent_dispositions_match_the_executable_absence_facts(self):
        document = committed()
        absent = document["help_only_unit_types"]
        for row in document["dialogs"]:
            for entry in row.get("census_disposition", {}).get("reasons", []):
                if entry["disposition"] != "absent_in_1_18":
                    continue
                with self.subTest(row["dialog_id"]):
                    for unit_type in entry["subjects"]:
                        self.assertNotIn(unit_type, document["unit_types"])
                        self.assertFalse(any(absent[unit_type].values()), unit_type)

    def test_ledger_owners_are_known_specific_obligations(self):
        features = {feature["id"] for feature in ledger()["features"]}
        obligations = {
            row["id"] for row in json.loads(REGISTER_PATH.read_text(encoding="utf-8"))["obligations"]
        }
        owned = 0
        for row in committed()["dialogs"]:
            for entry in row.get("census_disposition", {}).get("reasons", []):
                if entry["disposition"] != "ledger_owned":
                    self.assertNotIn("ledger_owner", entry)
                    continue
                owned += 1
                with self.subTest(row["dialog_id"]):
                    owner = entry["ledger_owner"]
                    self.assertTrue(owner.startswith("ledger:"), owner)
                    ledger_id = owner.removeprefix("ledger:")
                    self.assertIn(ledger_id, features)
                    self.assertNotIn(ledger_id, dialog_map.GENERIC_LEDGER_IDS)
                    self.assertIn(owner, obligations)
        self.assertEqual(owned, 15)

    def test_dispositions_claim_no_editor_or_resolution(self):
        for row in committed()["dialogs"]:
            disposition = row.get("census_disposition")
            if disposition is None:
                continue
            with self.subTest(row["dialog_id"]):
                self.assertEqual(row["status"], "unresolved")
                if disposition["code"] == "ledger_owned":
                    self.assertNotIn("implemented_editors", row)

    def test_validator_rejects_missing_or_altered_dispositions(self):
        dialogs = committed()["dialogs"]
        unresolved = next(i for i, row in enumerate(dialogs) if row["status"] == "unresolved")
        owned = next(
            i for i, row in enumerate(dialogs)
            if row.get("census_disposition", {}).get("code") == "ledger_owned"
        )
        resolved = next(i for i, row in enumerate(dialogs) if row["status"] == "resolved")
        cases = {
            "missing": (unresolved, lambda row: row.pop("census_disposition")),
            "unknown code": (unresolved, lambda row: row["census_disposition"].update(code="editor_exists")),
            "dropped reason": (unresolved, lambda row: row["census_disposition"].update(reasons=[])),
            "unknown owner": (
                owned,
                lambda row: row["census_disposition"]["reasons"][0].update(ledger_owner="ledger:nope"),
            ),
            "generic owner": (
                owned,
                lambda row: row["census_disposition"]["reasons"][0].update(
                    ledger_owner="ledger:toolkit-differential-acceptance"
                ),
            ),
            "resolved row disposition": (
                resolved, lambda row: row.update(census_disposition={"code": "ledger_owned", "reasons": []})
            ),
        }
        for label, (index, mutate) in cases.items():
            with self.subTest(label):
                document = committed()
                mutate(document["dialogs"][index])
                with self.assertRaises(ValueError):
                    dialog_map.validate_document(document)

    def test_owner_table_names_exactly_the_generic_ledger_dialogs(self):
        generic = {
            row["dialog_id"] for row in committed()["dialogs"]
            if any(reason["code"] == "generic_ledger_only" for reason in row["unresolved_reasons"])
        }
        self.assertEqual(set(dialog_map.DISPOSITION_LEDGER_OWNERS), generic)

    def test_builder_refuses_generic_or_unknown_owners(self):
        owners = dict(dialog_map.DISPOSITION_LEDGER_OWNERS)
        first = sorted(owners)[0]
        rows = committed()["dialogs"]
        for label, owner in (("generic", "toolkit-differential-acceptance"), ("unknown", "no-such-row")):
            with self.subTest(label), mock.patch.dict(
                dialog_map.DISPOSITION_LEDGER_OWNERS, {**owners, first: owner}, clear=True
            ):
                with self.assertRaisesRegex(ValueError, "not a specific ledger row"):
                    dialog_map.apply_census_dispositions(json.loads(json.dumps(rows)), ledger())

    def test_missing_or_stale_owner_fails_validation(self):
        owners = dict(dialog_map.DISPOSITION_LEDGER_OWNERS)
        first = sorted(owners)[0]
        cases = {
            "missing": ({k: v for k, v in owners.items() if k != first}, "without a census disposition"),
            "stale": ({**owners, "dialog:1.htm": "all-unit-parameter-encoding"}, "name no generic-ledger"),
        }
        for label, (table, message) in cases.items():
            with self.subTest(label), mock.patch.dict(
                dialog_map.DISPOSITION_LEDGER_OWNERS, table, clear=True
            ):
                with self.assertRaisesRegex(ValueError, message):
                    dialog_map.refresh_from_committed_facts(MAP_PATH)


if __name__ == "__main__":
    unittest.main()
