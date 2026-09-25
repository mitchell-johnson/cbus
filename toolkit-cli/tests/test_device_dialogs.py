"""Box1 RED/GREEN slice: device-dialog mapping registry (bead cbus-h22).

Starter registry only: enumerates the 118 census candidates, routes each to
a known ledger area, and holds every slot RED (pending/unassessed). No
parity claims, no CLI wiring, no capabilities.json status flips.
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest import mock

from cbus_toolkit import device_dialogs, differential

CENSUS_PATH = Path(__file__).resolve().parents[1] / "docs" / "toolkit-surface.json"

# Exact triage routing pin: dialog_id -> ledger area id. Membership-only
# checks miss mis-routing, so every dialog pins its expected ledger area.
EXPECTED_LEDGER_BY_DIALOG = {
    "dialog:11068.htm": "toolkit-differential-acceptance",
    "dialog:11057.htm": "toolkit-differential-acceptance",
    "dialog:11037.htm": "toolkit-differential-acceptance",
    "dialog:9286.htm": "toolkit-differential-acceptance",
    "dialog:9287.htm": "toolkit-differential-acceptance",
    "dialog:9289.htm": "toolkit-differential-acceptance",
    "dialog:9290.htm": "toolkit-differential-acceptance",
    "dialog:9205.htm": "dlt-edlt-widgets-and-labels",
    "dialog:9209.htm": "dlt-edlt-widgets-and-labels",
    "dialog:9210.htm": "dlt-edlt-widgets-and-labels",
    "dialog:18865.htm": "dlt-edlt-widgets-and-labels",
    "dialog:19973.htm": "toolkit-differential-acceptance",
    "dialog:19973_1.htm": "toolkit-differential-acceptance",
    "dialog:19973_2.htm": "toolkit-differential-acceptance",
    "dialog:19973_3.htm": "toolkit-differential-acceptance",
    "dialog:40007.htm": "toolkit-differential-acceptance",
    "dialog:9294.htm": "toolkit-differential-acceptance",
    "dialog:9300.htm": "toolkit-differential-acceptance",
    "dialog:9301.htm": "toolkit-differential-acceptance",
    "dialog:8449.htm": "toolkit-differential-acceptance",
    "dialog:8463.htm": "toolkit-differential-acceptance",
    "dialog:8476.htm": "toolkit-differential-acceptance",
    "dialog:9302.htm": "neo-core-key-presets",
    "dialog:9303.htm": "neo-core-key-presets",
    "dialog:9304.htm": "neo-core-key-presets",
    "dialog:9305.htm": "toolkit-differential-acceptance",
    "dialog:9311.htm": "toolkit-differential-acceptance",
    "dialog:9312.htm": "toolkit-differential-acceptance",
    "dialog:9313.htm": "toolkit-differential-acceptance",
    "dialog:9314.htm": "toolkit-differential-acceptance",
    "dialog:9315.htm": "toolkit-differential-acceptance",
    "dialog:9318.htm": "toolkit-differential-acceptance",
    "dialog:9319.htm": "toolkit-differential-acceptance",
    "dialog:9320.htm": "toolkit-differential-acceptance",
    "dialog:40001.htm": "toolkit-differential-acceptance",
    "dialog:8113.htm": "classic-key-presets",
    "dialog:8122.htm": "classic-key-presets",
    "dialog:8132.htm": "classic-key-presets",
    "dialog:8142.htm": "classic-key-presets",
    "dialog:8151.htm": "classic-key-presets",
    "dialog:9905.htm": "toolkit-differential-acceptance",
    "dialog:9926.htm": "toolkit-differential-acceptance",
    "dialog:9938.htm": "toolkit-differential-acceptance",
    "dialog:9967.htm": "toolkit-differential-acceptance",
    "dialog:9990.htm": "toolkit-differential-acceptance",
    "dialog:10004.htm": "toolkit-differential-acceptance",
    "dialog:10018.htm": "toolkit-differential-acceptance",
    "dialog:10032.htm": "toolkit-differential-acceptance",
    "dialog:10046.htm": "toolkit-differential-acceptance",
    "dialog:10059.htm": "toolkit-differential-acceptance",
    "dialog:10072.htm": "toolkit-differential-acceptance",
    "dialog:30004.htm": "toolkit-differential-acceptance",
    "dialog:30016.htm": "toolkit-differential-acceptance",
    "dialog:30028.htm": "toolkit-differential-acceptance",
    "dialog:30040.htm": "toolkit-differential-acceptance",
    "dialog:4455.htm": "toolkit-differential-acceptance",
    "dialog:4457.htm": "toolkit-differential-acceptance",
    "dialog:11068_1.htm": "toolkit-differential-acceptance",
    "dialog:11057_1.htm": "toolkit-differential-acceptance",
    "dialog:11037_1.htm": "toolkit-differential-acceptance",
    "dialog:10112.htm": "sensors-wizard-semantics",
    "dialog:19832.htm": "sensors-wizard-semantics",
    "dialog:11087.htm": "sensors-wizard-semantics",
    "dialog:15007.htm": "sensors-wizard-semantics",
    "dialog:9722.htm": "sensors-wizard-semantics",
    "dialog:5239.htm": "sensors-wizard-semantics",
    "dialog:14934.htm": "sensors-wizard-semantics",
    "dialog:17704.htm": "sensors-wizard-semantics",
    "dialog:17742.htm": "sensors-wizard-semantics",
    "dialog:17544.htm": "sensors-wizard-semantics",
    "dialog:8321.htm": "toolkit-differential-acceptance",
    "dialog:5116.htm": "all-unit-parameter-encoding",
    "dialog:9728.htm": "all-unit-parameter-encoding",
    "dialog:9792.htm": "all-unit-parameter-encoding",
    "dialog:9808.htm": "all-unit-parameter-encoding",
    "dialog:9824.htm": "all-unit-parameter-encoding",
    "dialog:9838.htm": "all-unit-parameter-encoding",
    "dialog:10157.htm": "all-unit-parameter-encoding",
    "dialog:12403.htm": "all-unit-parameter-encoding",
    "dialog:9688.htm": "all-unit-parameter-encoding",
    "dialog:9702.htm": "all-unit-parameter-encoding",
    "dialog:9646.htm": "all-unit-parameter-encoding",
    "dialog:5199.htm": "all-unit-parameter-encoding",
    "dialog:8064.htm": "all-unit-parameter-encoding",
    "dialog:8081.htm": "all-unit-parameter-encoding",
    "dialog:12053.htm": "all-unit-parameter-encoding",
    "dialog:12064.htm": "all-unit-parameter-encoding",
    "dialog:12074.htm": "all-unit-parameter-encoding",
    "dialog:7887.htm": "all-unit-parameter-encoding",
    "dialog:5213.htm": "all-unit-parameter-encoding",
    "dialog:5321.htm": "all-unit-parameter-encoding",
    "dialog:5296.htm": "all-unit-parameter-encoding",
    "dialog:12090.htm": "all-unit-parameter-encoding",
    "dialog:9617.htm": "all-unit-parameter-encoding",
    "dialog:11739.htm": "all-unit-parameter-encoding",
    "dialog:14052.htm": "sensors-wizard-semantics",
    "dialog:14054.htm": "sensors-wizard-semantics",
    "dialog:14053.htm": "sensors-wizard-semantics",
    "dialog:3850.htm": "thermostat-configuration",
    "dialog:3851.htm": "thermostat-configuration",
    "dialog:5392.htm": "toolkit-differential-acceptance",
    "dialog:5414.htm": "toolkit-differential-acceptance",
    "dialog:13447.htm": "toolkit-differential-acceptance",
    "dialog:13617.htm": "toolkit-differential-acceptance",
    "dialog:13623.htm": "toolkit-differential-acceptance",
    "dialog:15488.htm": "toolkit-differential-acceptance",
    "dialog:16301.htm": "toolkit-differential-acceptance",
    "dialog:10747.htm": "interface-discovery-and-setup",
    "dialog:10383.htm": "interface-discovery-and-setup",
    "dialog:10751.htm": "interface-discovery-and-setup",
    "dialog:1403.htm": "toolkit-differential-acceptance",
    "dialog:15426.htm": "toolkit-differential-acceptance",
    "dialog:2215.htm": "toolkit-differential-acceptance",
    "dialog:5532.htm": "toolkit-differential-acceptance",
    "dialog:12558.htm": "toolkit-differential-acceptance",
    "dialog:13872.htm": "toolkit-differential-acceptance",
    "dialog:13876.htm": "toolkit-differential-acceptance",
    "dialog:1613.htm": "toolkit-differential-acceptance",
}


def load_census_candidates() -> list[dict]:
    with CENSUS_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)["device_dialog_candidates"]


class DeviceDialogRegistryTests(unittest.TestCase):
    def test_pinned_count_and_nonempty(self):
        dialogs = device_dialogs.list_dialogs()
        self.assertGreaterEqual(len(dialogs), 1)
        self.assertEqual(len(dialogs), device_dialogs.EXPECTED_DIALOG_COUNT)
        self.assertEqual(len(dialogs), 118)

    def test_dialog_ids_match_census_order_exactly(self):
        candidates = load_census_candidates()
        expected_ids = [candidate["id"] for candidate in candidates]
        self.assertEqual(len(expected_ids), 118)
        dialogs = device_dialogs.list_dialogs()
        ids = [entry["dialog_id"] for entry in dialogs]
        self.assertEqual(len(set(ids)), len(ids))
        # Exact-order pin against the committed census: catches drift,
        # substitution, and reordering (a sorted() comparison never fails).
        self.assertEqual(ids, expected_ids)

    def test_census_fields_verbatim(self):
        candidates = load_census_candidates()
        by_id = {entry["dialog_id"]: entry for entry in device_dialogs.list_dialogs()}
        for candidate in candidates:
            with self.subTest(dialog=candidate["id"]):
                entry = by_id[candidate["id"]]
                self.assertEqual(entry["title"], candidate["title"])
                self.assertEqual(
                    entry["parent_context"], " / ".join(candidate["device_path"])
                )
                self.assertEqual(
                    entry["subtree_topics"], len(candidate["descendant_topic_ids"])
                )

    def test_every_dialog_maps_to_known_ledger_id(self):
        known = set(differential.ledger_area_ids(differential.load_ledger()))
        for entry in device_dialogs.list_dialogs():
            with self.subTest(dialog=entry["dialog_id"]):
                self.assertIn(entry["ledger_id"], known)

    def test_expected_ledger_id_per_dialog(self):
        dialogs = device_dialogs.list_dialogs()
        self.assertEqual(
            {entry["dialog_id"] for entry in dialogs},
            set(EXPECTED_LEDGER_BY_DIALOG),
        )
        for entry in dialogs:
            with self.subTest(dialog=entry["dialog_id"]):
                self.assertEqual(
                    entry["ledger_id"], EXPECTED_LEDGER_BY_DIALOG[entry["dialog_id"]]
                )

    def test_status_literals_track_differential(self):
        self.assertEqual(
            device_dialogs.DIALOG_PENDING, differential.DIFFERENTIAL_STATUSES[0]
        )
        self.assertEqual(
            device_dialogs.DIALOG_UNASSESSED, differential.DIFFERENTIAL_STATUSES[1]
        )

    def test_all_slots_start_red(self):
        for entry in device_dialogs.list_dialogs():
            with self.subTest(dialog=entry["dialog_id"]):
                self.assertEqual(
                    entry["differential_status"], differential.DIFFERENTIAL_STATUSES[0]
                )
                self.assertEqual(entry["evidence_paths"], [])
                for slot in differential.WORKFLOW_SLOTS:
                    self.assertEqual(
                        entry["workflows"][slot], differential.DIFFERENTIAL_STATUSES[1]
                    )
                for slot in differential.NEGATIVE_SLOTS:
                    self.assertEqual(
                        entry["negative_paths"][slot],
                        differential.DIFFERENTIAL_STATUSES[1],
                    )

    def test_dialog_status_roundtrip_all_rows_and_unknown_rejected(self):
        for entry in device_dialogs.list_dialogs():
            with self.subTest(dialog=entry["dialog_id"]):
                self.assertEqual(
                    device_dialogs.dialog_status(entry["dialog_id"]), entry
                )
        with self.assertRaises(KeyError):
            device_dialogs.dialog_status("dialog:no-such-dialog.htm")
        with self.assertRaises(KeyError):
            device_dialogs.dialog_status("")

    def test_matrix_by_ledger_covers_every_dialog(self):
        matrix = device_dialogs.matrix_by_ledger()
        total = sum(len(ids) for ids in matrix.values())
        self.assertEqual(total, 118)
        known = set(differential.ledger_area_ids(differential.load_ledger()))
        self.assertTrue(set(matrix) <= known)
        listed = {did for ids in matrix.values() for did in ids}
        self.assertEqual(
            listed, {entry["dialog_id"] for entry in device_dialogs.list_dialogs()}
        )

    def test_public_apis_reject_stale_ledger_area(self):
        ledger = differential.load_ledger()
        dropped = "toolkit-differential-acceptance"
        pruned = copy.deepcopy(ledger)
        pruned["features"] = [
            feature for feature in pruned["features"] if feature["id"] != dropped
        ]
        affected = next(
            dialog_id
            for dialog_id, ledger_id in EXPECTED_LEDGER_BY_DIALOG.items()
            if ledger_id == dropped
        )
        with mock.patch.object(
            differential, "load_ledger", return_value=pruned
        ):
            with self.assertRaises(KeyError):
                device_dialogs.list_dialogs()
            with self.assertRaises(KeyError):
                device_dialogs.dialog_status(affected)
            with self.assertRaises(KeyError):
                device_dialogs.matrix_by_ledger()

    def test_registry_load_preserves_unknown_ledger_fields_verbatim(self):
        import tempfile

        ledger = differential.load_ledger()
        probe = copy.deepcopy(ledger)
        probe["features"][0]["x_unrelated_probe"] = {"note": "verbatim"}
        probe["x_top_level_probe"] = [1, 2, 3]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capabilities-probe.json"
            path.write_text(json.dumps(probe), encoding="utf-8")
            reloaded = differential.load_ledger(path)
        self.assertEqual(reloaded["features"][0]["x_unrelated_probe"], {"note": "verbatim"})
        self.assertEqual(reloaded["x_top_level_probe"], [1, 2, 3])

    def test_registry_entries_are_copies(self):
        # Mutating a returned entry (workflows, negative paths, top-level
        # fields) must not leak into later reads.
        first_id = device_dialogs.list_dialogs()[0]["dialog_id"]
        first = device_dialogs.dialog_status(first_id)
        first["workflows"]["nominal_workflow"] = "accepted"
        first["negative_paths"]["invalid_input"] = "accepted"
        first["differential_status"] = "accepted"
        first["title"] = "mutated"
        first["evidence_paths"].append("evidence/probe.json")
        second = device_dialogs.dialog_status(first_id)
        self.assertEqual(
            second["workflows"]["nominal_workflow"],
            differential.DIFFERENTIAL_STATUSES[1],
        )
        self.assertEqual(
            second["negative_paths"]["invalid_input"],
            differential.DIFFERENTIAL_STATUSES[1],
        )
        self.assertEqual(
            second["differential_status"], differential.DIFFERENTIAL_STATUSES[0]
        )
        self.assertNotEqual(second["title"], "mutated")
        self.assertEqual(second["evidence_paths"], [])

    def test_no_completion_claims(self):
        ledger = differential.load_ledger()
        self.assertFalse(ledger["census_complete"])
        matrix = differential.build_matrix(ledger)
        self.assertFalse(matrix["complete"])
        self.assertEqual(matrix["accepted_areas"], 0)


if __name__ == "__main__":
    unittest.main()
