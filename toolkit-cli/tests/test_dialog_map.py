"""Device-dialog map: roster, input binding, determinism and explicit gaps."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import unittest

from cbus_toolkit import device_dialogs
from research import map_dialog_candidates as dialog_map


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "docs" / "toolkit-dialog-map.json"
REGISTER_PATH = ROOT / "src" / "cbus_toolkit" / "parity-obligations.json"


def committed() -> dict:
    return json.loads(MAP_PATH.read_text(encoding="utf-8"))


def facts_of(document: dict) -> dict:
    facts = {key: copy.deepcopy(document[key]) for key in dialog_map.FACT_KEYS}
    facts["inputs"] = {key: document["inputs"][key] for key in dialog_map.VENDOR_INPUTS}
    return facts


class DialogMapTests(unittest.TestCase):
    def test_all_118_dialogs_are_preserved_in_census_order(self):
        document = dialog_map.load_committed()
        surface = json.loads((ROOT / "docs/toolkit-surface.json").read_text(encoding="utf-8"))
        ids = [row["dialog_id"] for row in document["dialogs"]]
        self.assertEqual(len(ids), 118)
        self.assertEqual(ids, [row["id"] for row in surface["device_dialog_candidates"]])
        self.assertEqual(set(ids), {row["dialog_id"] for row in device_dialogs.list_dialogs()})
        counts = document["counts"]
        self.assertEqual(counts["dialogs"], 118)
        self.assertEqual(counts["resolved"] + counts["unresolved"], 118)

    def test_every_dialog_resolves_or_names_its_gap(self):
        for row in committed()["dialogs"]:
            with self.subTest(row["dialog_id"]):
                if row["status"] == "resolved":
                    self.assertEqual(row["unresolved_reasons"], [])
                    self.assertTrue(row["unit_types"])
                    self.assertTrue(row["form_resources"])
                    self.assertNotEqual(row["ledger_basis"], "generic")
                    self.assertFalse(set(row["ledger_ids"]) & dialog_map.GENERIC_LEDGER_IDS)
                else:
                    self.assertEqual(row["status"], "unresolved")
                    self.assertTrue(row["unresolved_reasons"])
                    for reason in row["unresolved_reasons"]:
                        self.assertEqual(reason["detail"], dialog_map.UNRESOLVED[reason["code"]])

    def test_offline_rebuild_is_deterministic_and_byte_identical(self):
        document = committed()
        first = dialog_map.render(dialog_map.build_document(facts_of(document)))
        second = dialog_map.render(dialog_map.build_document(facts_of(document)))
        self.assertEqual(first, second)
        self.assertEqual(first, MAP_PATH.read_text(encoding="utf-8"))

    @unittest.skipUnless(
        os.environ.get("CBUS_TOOLKIT_EXE")
        and dialog_map.default_catalog() is not None
        and os.environ.get("CBUS_UNITSPEC_DIR"),
        "Set CBUS_TOOLKIT_EXE, CBUS_CATALOG_PATH (or CBUS_LOCAL_CGATE_VENDOR) and "
        "CBUS_UNITSPEC_DIR to regenerate from original inputs",
    )
    def test_regeneration_from_original_inputs_matches_committed_map(self):
        exe = Path(os.environ["CBUS_TOOLKIT_EXE"])
        facts = dialog_map.extract_vendor_facts(
            exe,
            exe.with_suffix(".map"),
            dialog_map.default_catalog(),
            Path(os.environ["CBUS_UNITSPEC_DIR"]),
        )
        rendered = dialog_map.render(dialog_map.validate_document(dialog_map.build_document(facts)))
        self.assertEqual(rendered, MAP_PATH.read_text(encoding="utf-8"))

    def test_tampered_or_missing_input_digests_are_rejected(self):
        for name in (
            "toolkit_surface",
            "toolkit_executable_surface",
            "toolkit_executable",
            "toolkit_map",
            "unit_catalogue",
            "unitspec_directory",
        ):
            with self.subTest(name):
                document = committed()
                document["inputs"][name]["sha256"] = "0" * 63 + "g"
                with self.assertRaisesRegex(ValueError, f"input changed: {name}"):
                    dialog_map.validate_document(document)
        for name in ("toolkit_surface", "toolkit_map", "unit_catalogue"):
            with self.subTest(f"rehashed {name}"):
                document = committed()
                document["inputs"][name]["sha256"] = "1" * 64
                with self.assertRaisesRegex(ValueError, f"input changed: {name}"):
                    dialog_map.validate_document(document)
        document = committed()
        del document["inputs"]["unitspec_directory"]
        with self.assertRaises(ValueError):
            dialog_map.validate_document(document)
        document = committed()
        document["inputs"]["extra"] = {"sha256": "2" * 64}
        with self.assertRaisesRegex(ValueError, "incomplete or unexpected"):
            dialog_map.validate_document(document)

    def test_unresolved_rows_require_an_explicit_known_reason(self):
        unresolved = next(
            index for index, row in enumerate(committed()["dialogs"]) if row["status"] == "unresolved"
        )
        cases = {
            "empty reasons": lambda row: row.update(unresolved_reasons=[]),
            "unknown code": lambda row: row.update(
                unresolved_reasons=[{"code": "looks_fine", "detail": "x"}]
            ),
            "altered detail": lambda row: row["unresolved_reasons"][0].update(detail="x"),
            "extra reason field": lambda row: row["unresolved_reasons"][0].update(note="x"),
            "claimed resolution": lambda row: row.update(status="resolved"),
            "unknown status": lambda row: row.update(status="partial"),
        }
        for label, mutate in cases.items():
            with self.subTest(label):
                document = committed()
                mutate(document["dialogs"][unresolved])
                with self.assertRaises(ValueError):
                    dialog_map.validate_document(document)

    def test_offline_refresh_reproduces_the_committed_map(self):
        refreshed = dialog_map.refresh_from_committed_facts(MAP_PATH)
        self.assertEqual(dialog_map.render(refreshed), MAP_PATH.read_text(encoding="utf-8"))

    def test_roster_changes_and_edited_rows_are_rejected(self):
        document = committed()
        document["dialogs"].pop()
        with self.assertRaisesRegex(ValueError, "exactly 118"):
            dialog_map.validate_document(document)
        document = committed()
        document["dialogs"][0], document["dialogs"][1] = document["dialogs"][1], document["dialogs"][0]
        with self.assertRaisesRegex(ValueError, "roster"):
            dialog_map.validate_document(document)
        document = committed()
        resolved = next(row for row in document["dialogs"] if row["status"] == "resolved")
        resolved["ledger_ids"] = ["unit-hardware-acceptance"]
        with self.assertRaisesRegex(ValueError, "deterministic rebuild"):
            dialog_map.validate_document(document)
        document = committed()
        document["unit_types"]["KEYM4"]["node_managers"] = []
        with self.assertRaisesRegex(ValueError, "deterministic rebuild"):
            dialog_map.validate_document(document)

    def test_exact_ledger_types_must_stay_named_by_the_ledger(self):
        document = committed()
        surface = json.loads((ROOT / "docs/toolkit-surface.json").read_text(encoding="utf-8"))
        executable = json.loads(
            (ROOT / "docs/toolkit-executable-surface.json").read_text(encoding="utf-8")
        )
        ledger = json.loads((ROOT / "src/cbus_toolkit/capabilities.json").read_text(encoding="utf-8"))
        feature = next(
            row for row in ledger["features"] if row["id"] == "dlt-edlt-widgets-and-labels"
        )
        feature["limits"] = feature["limits"].replace("KEYGL5", "KEYGLX")
        triage = {row["dialog_id"]: row["ledger_id"] for row in device_dialogs.list_dialogs()}
        with self.assertRaisesRegex(ValueError, "no longer name KEYGL5"):
            dialog_map.assemble_dialogs(surface, executable, ledger, facts_of(document), triage)

    def test_key_preset_exact_types_follow_the_family_receipt(self):
        admitted = dialog_map._admitted_key_preset_types()
        self.assertTrue({"KEY1", "KEY2", "KEY4"} <= admitted["classic-key-presets"])
        self.assertTrue(
            {"KEYA3", "KEYB4", "KEYE1", "KEYM4"} <= admitted["neo-core-key-presets"]
        )

    def test_static_factory_recovery_is_pinned(self):
        document = committed()
        factory = document["unit_factory"]
        self.assertEqual(factory["unit_call_sites"], 427)
        self.assertEqual(factory["unit_registrations"], 425)
        self.assertEqual(factory["node_manager_call_sites"], 269)
        self.assertEqual(factory["node_manager_registrations"], 267)
        self.assertFalse(factory["original_executed"])
        self.assertEqual(
            {row["procedure"] for row in factory["unresolved_call_sites"]},
            {
                "CIS_TRegisterExtraUnits.TRegisterExtraUnits.RegisterUnitType",
                "CIS_TRegisterExtraUnits.TRegisterExtraUnits.RegisterTypeCompatibleUnits",
            },
        )
        self.assertEqual(
            document["unit_types"]["KEYA1"]["factory_registrations"],
            [
                {"max_firmware": "1.5.02", "min_firmware": "1.3.01", "unit_class": "TKEYA1_A"},
                {"max_firmware": "2.9.99", "min_firmware": "1.5.03", "unit_class": "TKEYA1"},
            ],
        )
        self.assertEqual(document["unit_types"]["KEYA1"]["node_managers"], ["TnmKEYA1"])
        self.assertEqual(document["node_managers"]["TnmKEYA1"]["directors"], ["TddKeyM8", "TddNeoPro"])
        self.assertEqual(document["directors"]["TddNeoPro"]["dialog_forms"], ["TfrmNeoPro"])

    def test_unit_dialog_factory_and_common_director_fallback_are_pinned(self):
        document = committed()
        factory = document["unit_dialog_factory"]
        self.assertEqual(factory["call_sites"], 11)
        self.assertEqual(factory["unresolved_call_sites"], [])
        self.assertFalse(factory["original_executed"])
        self.assertEqual(
            {(row["unit_type"], row["form_class"]) for row in factory["registrations"]},
            {
                ("IOPE1R1", "TfrmIOPE"), ("IOPE2R2", "TfrmIOPE"), ("IOPE2C4", "TfrmIOPE"),
                ("DMXDO12", "TfrmDMXGateway"), ("DIMAR3", "TfrmArchitecturalDimmer"),
                ("DIMAR6", "TfrmArchitecturalDimmer"), ("DIMAR12", "TfrmArchitecturalDimmer"),
                ("KEYGL5", "TfrmKEYGL5"), ("SENCT4", "TfrmSENCT4"), ("SENTEMP4", "TfrmPC_RDTS"),
                ("C12DIMAR", "TfrmCArchitecturalDimmer"),
            },
        )
        fallback = factory["director_fallback"]
        self.assertEqual(
            fallback["director_lookup_order"],
            ["by_object", "by_unit_type", "by_descriptor:CommonCBusUnit"],
        )
        self.assertEqual(fallback["director"], "TddCommonCBusUnit")
        by_id = {row["dialog_id"]: row for row in document["dialogs"]}
        for dialog_id, form in (
            ("dialog:14052.htm", "TFRMIOPE"),
            ("dialog:8064.htm", "TFRMARCHITECTURALDIMMER"),
            ("dialog:11739.htm", "TFRMDMXGATEWAY"),
            ("dialog:18865.htm", "TFRMKEYGL5"),
            ("dialog:14934.htm", "TFRMSENCT4"),
        ):
            with self.subTest(dialog_id):
                row = by_id[dialog_id]
                self.assertEqual(row["status"], "resolved")
                self.assertEqual(row["form_resources"], [form])
                self.assertEqual(
                    {unit["dispatch"] for unit in row["unit_types"]}, {"common_director_unit_dialog"}
                )
                self.assertEqual(row["directors"], ["TddCommonCBusUnit"])

    def test_shared_fallback_director_does_not_route_ledger_rows(self):
        document = committed()
        by_id = {row["dialog_id"]: row for row in document["dialogs"]}
        # DIMAR and DMX share only the CommonCBusUnit fallback with IOPE and
        # KEYGL5; they keep their own triage row.
        for dialog_id in ("dialog:8064.htm", "dialog:11739.htm"):
            self.assertEqual(by_id[dialog_id]["ledger_ids"], ["all-unit-parameter-encoding"])
            self.assertEqual(by_id[dialog_id]["ledger_basis"], "help_branch_triage")

    def test_executable_help_links_resolve_help_gaps(self):
        document = committed()
        links = {row["key"]: row["context_id"] for row in document["help_links"]["entries"]}
        self.assertEqual(len(document["help_links"]["entries"]), 197)
        self.assertEqual((links["TKEYM8"], links["TKEYA8"]), (5062, 5087))
        self.assertEqual((links["TPC_TSA"], links["TPC_TSB"]), (2562, 2964))
        by_id = {row["dialog_id"]: row for row in document["dialogs"]}
        neo8 = by_id["dialog:9304.htm"]
        self.assertEqual(neo8["unit_type_selection"], "executable_help_link_conflict")
        self.assertEqual([unit["unit_type"] for unit in neo8["unit_types"]], ["KEYM8"])
        self.assertEqual(neo8["other_help_unit_type_candidates"], ["KEYA8"])
        self.assertEqual(neo8["status"], "resolved")
        for dialog_id, types in (
            ("dialog:3850.htm", ["PC_TSA", "PC_TSA5"]),
            ("dialog:3851.htm", ["PC_TSB", "PC_TSB5"]),
        ):
            with self.subTest(dialog_id):
                row = by_id[dialog_id]
                self.assertEqual(row["unit_type_selection"], "executable_help_link_none")
                self.assertEqual([unit["unit_type"] for unit in row["unit_types"]], types)
                self.assertEqual(row["ledger_ids"], ["thermostat-configuration"])
                self.assertEqual(row["status"], "resolved")

    def test_help_only_unit_types_are_absent_from_the_executable(self):
        document = committed()
        absent = document["help_only_unit_types"]
        self.assertEqual(sorted(absent), ["KEYH5", "PC_INTU", "WPAD2D1", "WPAD2R1"])
        for name, presence in absent.items():
            self.assertEqual(presence, {"utf16_literal": False, "short_string": False}, name)
        by_id = {row["dialog_id"]: row for row in document["dialogs"]}
        for dialog_id, subjects in (
            ("dialog:19973.htm", ["KEYH5"]),
            ("dialog:10747.htm", ["PC_INTU"]),
            ("dialog:12558.htm", ["WPAD2D1", "WPAD2R1"]),
        ):
            reason = by_id[dialog_id]["unresolved_reasons"][0]
            self.assertEqual(reason["code"], "help_unit_type_absent_from_executable")
            self.assertEqual(reason["subjects"], subjects)

    def test_unresolved_roster_is_pinned(self):
        document = committed()
        self.assertEqual((document["counts"]["resolved"], document["counts"]["unresolved"]), (101, 17))
        self.assertEqual(
            document["counts"]["unresolved_reasons"],
            {"generic_ledger_only": 15, "help_unit_type_absent_from_executable": 3},
        )
        for row in document["dialogs"]:
            for reason in row["unresolved_reasons"]:
                with self.subTest(row["dialog_id"], code=reason["code"]):
                    self.assertTrue(reason["subjects"])

    def test_control_coverage_is_derived_from_committed_receipts(self):
        document = committed()
        table = {row["dialog_id"]: row for row in document["control_coverage_table"]}
        expected = {
            "dialog:9792.htm": (["din-output-settings"], 16, 27),
            "dialog:14052.htm": (["iope-settings"], 28, 196),
            "dialog:13876.htm": (["wireless-gateway-remote-switch"], 32, 41),
        }
        for dialog_id, (editors, mapped, total) in expected.items():
            with self.subTest(dialog_id):
                row = table[dialog_id]
                self.assertEqual(row["editors"], editors)
                self.assertEqual((row["controls_mapped"], row["controls_total"]), (mapped, total))
                self.assertEqual(row["basis"], "control_receipt")
        for dialog_id in ("dialog:11087.htm", "dialog:10112.htm", "dialog:3850.htm", "dialog:9303.htm",
                          "dialog:11068.htm", "dialog:18865.htm"):
            with self.subTest(dialog_id):
                self.assertEqual(table[dialog_id]["controls_mapped"], 0)
                self.assertEqual(table[dialog_id]["basis"], "no_control_level_receipt")
        by_id = {row["dialog_id"]: row for row in document["dialogs"]}
        iope = by_id["dialog:14052.htm"]
        self.assertEqual(iope["implemented_editors"][0]["modules"][0], "src/cbus_toolkit/iope_settings.py")
        mapped = {(row["control"], row["parameter"]) for row in iope["control_coverage"]["mapped_controls"]}
        self.assertIn(("cmbLongPressTime", "LongPressTime"), mapped)
        self.assertIn(("rgSensor2Enabled", "SensorNEnabled"), mapped)
        self.assertEqual(
            by_id["dialog:13876.htm"]["implemented_editors"][0]["link_basis"], "receipt_names_dialog"
        )
        for editor in dialog_map.IMPLEMENTED_EDITORS:
            for path in editor["modules"] + [editor["documentation"]] + editor["receipts"]:
                self.assertTrue((ROOT / path).is_file(), path)

    def test_control_patterns_expand_ranges_alternatives_and_indices(self):
        def names(text: str, candidates: list[str]) -> list[str]:
            patterns = dialog_map._control_patterns(text)
            return [name for name in candidates if any(p.fullmatch(name) for p in patterns)]

        self.assertEqual(
            names("chkLA1..chkLA4", ["chkLA1", "chkLA4", "chkLA5"]), ["chkLA1", "chkLA4"]
        )
        self.assertEqual(
            names("cmbGlobal1..4RecallLevel", ["cmbGlobal2RecallLevel", "cmbGlobal5RecallLevel"]),
            ["cmbGlobal2RecallLevel"],
        )
        self.assertEqual(
            names("cmbRampRateGlobal1/2/3, cmbRampRateScene",
                  ["cmbRampRateGlobal3", "cmbRampRateScene", "cmbRampRateGlobal4"]),
            ["cmbRampRateGlobal3", "cmbRampRateScene"],
        )
        self.assertEqual(
            names("rgSensorNEnabled (Disabled when On/Off)", ["rgSensor2Enabled", "rgSensorEnabled"]),
            ["rgSensor2Enabled"],
        )
        self.assertEqual(names("cmbKeyKFunction", ["cmbKey10Function", "cmbKeyFunction"]), ["cmbKey10Function"])

    def test_stale_receipt_form_digest_is_rejected(self):
        executable = json.loads(
            (ROOT / "docs/toolkit-executable-surface.json").read_text(encoding="utf-8")
        )
        for resource in executable["resources"]:
            if resource["resource_name"] == "TFRMIOPEGLOBAL":
                resource["resource_sha256"] = "0" * 64
        editor = next(row for row in dialog_map.IMPLEMENTED_EDITORS if row["id"] == "iope-settings")
        with self.assertRaisesRegex(ValueError, "stale form resource TFRMIOPEGLOBAL"):
            dialog_map._receipt_form_resources([editor], executable)

    def test_committed_map_carries_identifiers_not_vendor_content(self):
        document = committed()
        allowed_type_keys = {
            "alternative_catalogue_numbers",
            "catalogue_numbers",
            "catalogue_revisions",
            "factory_registrations",
            "node_managers",
            "spec_files",
        }
        for name, entry in document["unit_types"].items():
            self.assertEqual(set(entry), allowed_type_keys, name)
        text = MAP_PATH.read_text(encoding="utf-8")
        for forbidden in ('"description"', '"title"', '"Description"', '"DefaultValue"', "Parameters"):
            self.assertNotIn(forbidden, text)

    def test_parity_register_routes_dialogs_through_the_map(self):
        register = json.loads(REGISTER_PATH.read_text(encoding="utf-8"))
        document = committed()
        by_id = {row["dialog_id"]: row for row in document["dialogs"]}
        dialogs = [item for item in register["scope_items"] if item["kind"] == "dialog"]
        self.assertEqual(len(dialogs), 118)
        for item in dialogs:
            row = by_id[item["source_id"]]
            with self.subTest(item["source_id"]):
                self.assertEqual(
                    item["obligation_ids"], [f"ledger:{ledger_id}" for ledger_id in row["ledger_ids"]]
                )
                self.assertEqual(item["dialog_map_status"], row["status"])
                self.assertEqual(
                    item.get("dialog_map_unresolved", []),
                    [reason["code"] for reason in row["unresolved_reasons"]],
                )
        resolved_forms = {
            resource for row in document["dialogs"] if row["status"] == "resolved"
            for resource in row["form_resources"]
        }
        forms = {
            item["source_id"]: item for item in register["scope_items"]
            if item["kind"] == "executable_form"
        }
        for resource in resolved_forms:
            self.assertNotIn("ledger:toolkit-surface-census", forms[resource]["obligation_ids"])
            self.assertTrue(forms[resource]["dialog_ids"])
        self.assertEqual(
            register["source_digests"]["toolkit_dialog_map"],
            dialog_map.digest(MAP_PATH),
        )


if __name__ == "__main__":
    unittest.main()
