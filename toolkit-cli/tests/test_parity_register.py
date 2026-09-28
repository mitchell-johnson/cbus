from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from cbus_toolkit import parity
from research import build_parity_register as register_builder


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_REPORT = (json.dumps({
    "format": "cbus-parity-test-report-v1",
    "result": "passed",
    "source_revision": "1" * 40,
    "command": "python -m pytest tests/test_one.py",
    "exit_code": 0,
    "cases": [{
        "id": "tests/test_one.py::test_one",
        "result": "passed",
        "obligation_ids": ["obligation:one"],
        "dimensions": list(parity.REQUIRED_DIMENSIONS),
    }],
}, sort_keys=True) + "\n").encode()


def record_digest(record: dict) -> str:
    content = {key: value for key, value in record.items() if key != "record_sha256"}
    return sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def write_fixture_report(record: dict, root: Path) -> None:
    """Keep a synthetic execution report bound to its changed test decision."""
    report = {
        "format": "cbus-parity-test-report-v1",
        "result": record["result"],
        "source_revision": record["source_revision"],
        "command": record["command"],
        "exit_code": record["exit_code"],
        "cases": [{
            "id": record["test_ids"][0],
            "result": record["result"],
            "obligation_ids": record["obligation_ids"],
            "dimensions": record["dimensions"],
            "applicability_receipts": record.get("applicability_receipts", []),
            "scope_disposition_receipts": record["scope_disposition_receipts"],
        }],
    }
    raw = (json.dumps(report, sort_keys=True) + "\n").encode()
    path = record["report_verification"]["path"]
    destination = root / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(raw)
    next(artifact for artifact in record["artifacts"] if artifact["path"] == path)[
        "sha256"
    ] = sha256(raw).hexdigest()
    record["record_sha256"] = record_digest(record)


def fixture_documents() -> tuple[dict, dict, dict, bytes]:
    artifact = FIXTURE_REPORT
    evidence_record = {
        "id": "evidence:one",
        "obligation_ids": ["obligation:one"],
        "scope_disposition_receipts": [],
        "dimensions": list(parity.REQUIRED_DIMENSIONS),
        "result": "passed",
        "test_ids": ["tests/test_one.py::test_one"],
        "environment": {
            "kind": "physical",
            "identity": "fixture environment",
            "hardware_refs": ["fixture-device"],
        },
        "oracle": {
            "target": "fixture original",
            "artifact_sha256": sha256(b"fixture original").hexdigest(),
        },
        "source_revision": "1" * 40,
        "command": "python -m pytest tests/test_one.py",
        "exit_code": 0,
        "report_verification": {
            "format": "cbus-parity-test-report-v1",
            "path": "result.txt",
        },
        "artifacts": [
            {
                "role": "input",
                "path": "oracle.txt",
                "sha256": sha256(b"fixture original").hexdigest(),
            },
            {
                "role": "report",
                "path": "result.txt",
                "sha256": sha256(artifact).hexdigest(),
            }
        ],
        "skips": [],
    }
    evidence_record["record_sha256"] = record_digest(evidence_record)
    evidence = {"schema_version": 1, "target": "fixture", "records": [evidence_record]}
    evidence_raw = (json.dumps(evidence, indent=2) + "\n").encode()
    ledger = {
        "target": "fixture",
        "features": [
            {"id": "area", "status": "implemented", "evidence": [], "limits": "fixture"}
        ]
    }
    obligation = {
        "id": "obligation:one",
        "ledger_id": "area",
        "work_item_ids": ["P0.05"],
        "definition_status": "defined",
        "implementation_status": "implemented",
        "applicability_status": "resolved",
        "outcome": "one complete fixture outcome",
        "source_refs": ["fixture"],
        "acceptance": {dimension: "accepted" for dimension in parity.REQUIRED_DIMENSIONS},
        "evidence_ids": ["evidence:one"],
    }
    register = {
        "schema_version": 1,
        "target": "fixture",
        "denominator_version": "fixture-1",
        "census_complete": True,
        "source_digests": {"fixture": sha256(b"fixture").hexdigest()},
        "evidence_bundle_sha256": sha256(evidence_raw).hexdigest(),
        "work_item_ids": sorted(parity.WORK_ITEM_IDS),
        "source_inventory": [
            {"id": "fixture", "scope_kind": "fixture", "count": 1, "resolved": True}
        ],
        "scope_items": [
            {
                "id": "scope:one",
                "kind": "fixture",
                "source_id": "one",
                "disposition": "functional_obligation",
                "obligation_ids": ["obligation:one"],
            }
        ],
        "obligations": [obligation],
    }
    return register, evidence, ledger, evidence_raw


def packaged_documents() -> tuple[dict, dict, dict, bytes, dict, bytes, bytes]:
    package = ROOT / "src/cbus_toolkit"
    register = json.loads((package / "parity-obligations.json").read_bytes())
    evidence_raw = (package / "parity-evidence.json").read_bytes()
    contract_raw = (package / "cgate-contract-inventory.json").read_bytes()
    ledger_raw = (package / "capabilities.json").read_bytes()
    return (
        register,
        json.loads(evidence_raw),
        json.loads(ledger_raw),
        evidence_raw,
        json.loads(contract_raw),
        contract_raw,
        ledger_raw,
    )


def evaluate_packaged_change(register: dict) -> dict:
    _, evidence, ledger, evidence_raw, contracts, contract_raw, ledger_raw = packaged_documents()
    return parity.evaluate(
        register,
        evidence,
        ledger,
        evidence_raw=evidence_raw,
        ledger_raw=ledger_raw,
        cgate_contract_inventory=contracts,
        cgate_contract_raw=contract_raw,
    )


class ParityRegisterTests(unittest.TestCase):
    def test_completed_roadmap_item_remains_in_work_item_roster(self):
        roadmap = register_builder.ROADMAP_PATH.read_text(encoding="utf-8")
        self.assertRegex(roadmap, r"(?m)^- \[[ xX]\] \*\*P9\.01\*\*")
        completed = re.sub(
            r"(?m)^- \[[ xX]\] (?=\*\*P9\.01\*\*)",
            "- [x] ",
            roadmap,
            count=1,
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "roadmap.md"
            path.write_text(completed, encoding="utf-8")
            with patch.object(register_builder, "ROADMAP_PATH", path):
                work_items, _ = register_builder.roadmap_maps()
        self.assertIn("P9.01", work_items["P9"])

    def setUp(self):
        self.artifact_folder = TemporaryDirectory()
        self.addCleanup(self.artifact_folder.cleanup)
        self.artifact_root = Path(self.artifact_folder.name)
        (self.artifact_root / "oracle.txt").write_bytes(b"fixture original")
        (self.artifact_root / "result.txt").write_bytes(FIXTURE_REPORT)

    def test_packaged_register_accounts_for_all_committed_source_surfaces(self):
        ledger = json.loads((ROOT / "src/cbus_toolkit/capabilities.json").read_text())
        report = parity.evaluate_packaged(ledger)
        self.assertFalse(report["complete"])
        self.assertFalse(report["denominator_ready"])
        self.assertFalse(report["functional_percent_available"])
        self.assertIsNone(report["obligations"]["implementation_percent"])
        self.assertIsNone(report["obligations"]["accepted_percent"])
        self.assertIsNone(
            report["acceptance_by_dimension"]["original_differential"]["percent"]
        )
        self.assertEqual(report["obligations"]["total"], 484)
        self.assertEqual(report["obligations"]["defined"], 3)
        self.assertEqual(report["obligations"]["accepted"], 0)
        self.assertEqual(report["legacy_category_summary"]["implemented"], 18)
        self.assertEqual(report["legacy_category_summary"]["implemented_percent"], 46.15)
        self.assertFalse(report["legacy_category_summary"]["functionality_estimate"])
        self.assertEqual(
            report["scope_items"]["by_kind"],
            {
                "anchor": 1349,
                "cgate_primary_path": 431,
                "cgate_supplement_path": 11,
                "dialog": 118,
                "executable_control": 10102,
                "executable_event": 1892,
                "executable_form": 412,
                "heading": 3680,
                "macro_leaf": 179,
                "public_command": 209,
                "topic": 3767,
                "unindexed_html": 6,
            },
        )
        self.assertEqual(report["scope_items"]["total"], 22156)
        self.assertEqual(report["scope_items"]["unresolved"], 22156)
        self.assertEqual(report["source_inventory"]["total_domains"], 15)
        self.assertEqual(report["source_inventory"]["resolved_domains"], 0)
        self.assertEqual(report["evidence_records"], 3)
        self.assertEqual(
            report["acceptance_by_dimension"]["original_differential"]["accepted"], 3
        )
        self.assertEqual(report["acceptance_by_dimension"]["physical"]["not_applicable"], 3)
        self.assertEqual(report["cgate_contracts"]["paths"], 442)
        self.assertEqual(
            report["cgate_contracts"]["subaxis_status"][
                "selector_grammar.argument_arity"
            ],
            {"resolved": 5, "unresolved": 437},
        )
        self.assertEqual(
            report["cgate_contracts"]["subaxis_status"][
                "implementation_acceptance.functional_acceptance"
            ],
            {"unresolved": 442},
        )

    def test_packaged_evidence_artifacts_match_source_checkout(self):
        register, evidence, ledger, evidence_raw, contracts, contract_raw, ledger_raw = packaged_documents()
        report = parity.evaluate(
            register,
            evidence,
            ledger,
            evidence_raw=evidence_raw,
            ledger_raw=ledger_raw,
            cgate_contract_inventory=contracts,
            cgate_contract_raw=contract_raw,
            artifact_root=ROOT,
        )
        self.assertEqual(report["evidence_records"], len(evidence["records"]))

    def test_session_function_pilot_has_scoped_differential_and_physical_decisions(self):
        register, evidence, _, _, _, _, _ = packaged_documents()
        self.assertEqual(len(evidence["records"]), 3)
        self.assertEqual(evidence["records"][0]["dimensions"], ["original_differential"])
        self.assertEqual(evidence["records"][1]["dimensions"], ["original_differential"])
        self.assertEqual(evidence["records"][2]["dimensions"], [])
        self.assertEqual(len(evidence["records"][2]["applicability_receipts"]), 3)
        self.assertFalse(register["census_complete"])
        functions = {
            item["source_id"]: item
            for item in register["obligations"]
            if item.get("kind") == "cgate_function"
        }
        self.assertEqual(set(functions), set(parity.CGATE_SESSION_PILOT_IDS))
        for path, obligation in functions.items():
            with self.subTest(path=path):
                self.assertEqual(obligation["id"], parity.CGATE_SESSION_PILOT_IDS[path])
                self.assertEqual(obligation["ledger_id"], "cgate-command-transport")
                self.assertEqual(obligation["definition_status"], "defined")
                self.assertEqual(obligation["implementation_status"], "in_progress")
                self.assertEqual(obligation["applicability_status"], "unresolved")
                self.assertEqual(
                    obligation["applicability"]["physical_candidate"],
                    "not_applicable_verified",
                )
                self.assertEqual(obligation["acceptance"]["original_differential"], "accepted")
                self.assertEqual(obligation["acceptance"]["physical"], "not_applicable")
                self.assertEqual(
                    {value for key, value in obligation["acceptance"].items()
                     if key not in {"original_differential", "physical"}}, {"unassessed"}
                )
                self.assertEqual(obligation["evidence_ids"],
                                 ["evidence:cgate-session-id-loopback-differential-v1",
                                  "evidence:cgate-session-id-tagged-wire-differential-v1",
                                  "evidence:cgate-session-id-physical-applicability-v1"])
                broad = next(
                    item for item in register["obligations"]
                    if item.get("kind") == "cgate_path" and item["source_id"] == path
                )
                self.assertEqual(broad["definition_status"], "provisional")

    def test_session_differential_acceptance_rejects_missing_or_stale_receipt(self):
        with TemporaryDirectory() as folder:
            missing = Path(folder, "missing.json")
            with patch.object(register_builder, "SESSION_DIFFERENTIAL_PATH", missing):
                with self.assertRaisesRegex(ValueError, "receipt is missing"):
                    register_builder.session_differential_evidence()

            receipt = json.loads(register_builder.SESSION_DIFFERENTIAL_PATH.read_text())
            receipt["source_fingerprint"]["rust/cbus-cgate/src/main.rs"] = "0" * 64
            stale = Path(folder, "stale.json")
            stale.write_text(json.dumps(receipt))
            with patch.object(register_builder, "SESSION_DIFFERENTIAL_PATH", stale):
                with self.assertRaisesRegex(ValueError, "source fingerprint is stale"):
                    register_builder.session_differential_evidence()

            receipt = json.loads(register_builder.SESSION_DIFFERENTIAL_PATH.read_text())
            receipt["cases"][0]["result"] = "failed"
            partial = Path(folder, "partial.json")
            partial.write_text(json.dumps(receipt))
            with patch.object(register_builder, "SESSION_DIFFERENTIAL_PATH", partial):
                with self.assertRaisesRegex(ValueError, "case evidence changed"):
                    register_builder.session_differential_evidence()

    def test_tagged_wire_acceptance_rejects_missing_stale_and_tampered_receipts(self):
        with TemporaryDirectory() as folder:
            missing = Path(folder, "missing.json")
            with patch.object(register_builder, "TAGGED_SESSION_DIFFERENTIAL_PATH", missing):
                with self.assertRaisesRegex(ValueError, "tagged SESSION_ID differential receipt is missing"):
                    register_builder.session_tagged_wire_evidence()

            receipt = json.loads(register_builder.TAGGED_SESSION_DIFFERENTIAL_PATH.read_text())
            receipt["source_fingerprint"]["rust/cbus-cgate/src/main.rs"] = "0" * 64
            stale = Path(folder, "stale.json")
            stale.write_text(json.dumps(receipt))
            with patch.object(register_builder, "TAGGED_SESSION_DIFFERENTIAL_PATH", stale):
                with self.assertRaisesRegex(ValueError, "source fingerprint is stale"):
                    register_builder.session_tagged_wire_evidence()

            receipt = json.loads(register_builder.TAGGED_SESSION_DIFFERENTIAL_PATH.read_text())
            receipt["cases"][2]["rust_wire_reply"][0] = (
                receipt["cases"][2]["rust_wire_reply"][0].replace("[502]", "[999]")
            )
            altered = Path(folder, "altered.json")
            altered.write_text(json.dumps(receipt))
            with patch.object(register_builder, "TAGGED_SESSION_DIFFERENTIAL_PATH", altered):
                with self.assertRaisesRegex(ValueError, "raw wire changed"):
                    register_builder.session_tagged_wire_evidence()

    def test_packaged_tagged_wire_rejects_forged_raw_prefix_with_updated_digests(self):
        _, evidence, _, _, _, _, _ = packaged_documents()
        evidence = json.loads(json.dumps(evidence))
        tagged = evidence["records"][1]
        raw = json.loads(register_builder.TAGGED_SESSION_DIFFERENTIAL_PATH.read_text())
        raw["cases"][2]["rust_wire_reply"][0] = raw["cases"][2]["rust_wire_reply"][0].replace("[502]", "[999]")
        with TemporaryDirectory() as folder:
            root = Path(folder)
            for artifact in tagged["artifacts"]:
                source = ROOT / artifact["path"]
                destination = root / artifact["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.read_bytes())
            report_path = root / tagged["report_verification"]["path"]
            report_path.write_text(json.dumps(raw))
            next(item for item in tagged["artifacts"] if item["role"] == "report")["sha256"] = sha256(report_path.read_bytes()).hexdigest()
            tagged["record_sha256"] = record_digest(tagged)
            with self.assertRaisesRegex(ValueError, "tagged case 2 lost wire framing"):
                parity._validate_execution_report(tagged, raw, artifact_root=root)

    def test_session_physical_applicability_rejects_stale_or_missing_receipt(self):
        with TemporaryDirectory() as folder:
            missing = Path(folder, "missing.json")
            with patch.object(register_builder, "SESSION_PHYSICAL_PATH", missing):
                with self.assertRaises(FileNotFoundError):
                    register_builder.session_physical_applicability_evidence()

            report = json.loads(register_builder.SESSION_PHYSICAL_PATH.read_text())
            report["source_inputs"]["contract_inventory"] = "0" * 64
            stale = Path(folder, "stale.json")
            stale.write_text(json.dumps(report))
            with patch.object(register_builder, "SESSION_PHYSICAL_PATH", stale):
                with self.assertRaisesRegex(ValueError, "report is stale"):
                    register_builder.session_physical_applicability_evidence()

            report = json.loads(register_builder.SESSION_PHYSICAL_PATH.read_text())
            report["cases"][0]["applicability_receipts"][0]["decision"] = "accepted"
            altered = Path(folder, "altered.json")
            altered.write_text(json.dumps(report))
            with patch.object(register_builder, "SESSION_PHYSICAL_PATH", altered):
                with self.assertRaisesRegex(ValueError, "report is stale"):
                    register_builder.session_physical_applicability_evidence()

    def test_session_function_pilot_rejects_broken_packaged_anchors(self):
        def first_function(register):
            return next(
                item for item in register["obligations"]
                if item.get("kind") == "cgate_function"
            )

        register, *_ = packaged_documents()
        del first_function(register)["source_anchor"]
        with self.assertRaisesRegex(ValueError, "requires an exact public-help source anchor"):
            evaluate_packaged_change(register)

        register, *_ = packaged_documents()
        first_function(register)["source_anchor"]["syntax_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "differs from its source and broad-ledger anchors"):
            evaluate_packaged_change(register)

        register, *_ = packaged_documents()
        function = first_function(register)
        public_scope = next(
            item for item in register["scope_items"]
            if item["id"] == function["source_scope_item_ids"][0]
        )
        public_scope["obligation_ids"].remove(function["id"])
        with self.assertRaisesRegex(ValueError, "differs from its source and broad-ledger anchors"):
            evaluate_packaged_change(register)

        register, *_ = packaged_documents()
        first_function(register)["native_oracle"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "native acceptance anchor is stale or missing"):
            evaluate_packaged_change(register)

        register, *_ = packaged_documents()
        first_function(register)["evidence_ids"].remove(
            "evidence:cgate-session-id-physical-applicability-v1"
        )
        with self.assertRaisesRegex(ValueError, "lacks a passed not-applicable decision"):
            evaluate_packaged_change(register)

    def test_session_function_pilot_builder_rejects_stale_or_missing_original_sources(self):
        surface = json.loads((ROOT / "docs/toolkit-surface.json").read_text())
        contracts = json.loads((ROOT / "src/cbus_toolkit/cgate-contract-inventory.json").read_text())
        by_path = {item["path"]: item for item in contracts["contracts"]}
        self.assertEqual(len(register_builder.functional_pilot(surface, by_path)), 3)

        with TemporaryDirectory() as folder:
            native = Path(folder, "native.json")
            native.write_bytes(register_builder.NATIVE_SESSION_PATH.read_bytes() + b" ")
            with patch.object(register_builder, "NATIVE_SESSION_PATH", native):
                with self.assertRaisesRegex(ValueError, "native acceptance source is stale"):
                    register_builder.functional_pilot(surface, by_path)
            native.unlink()
            with patch.object(register_builder, "NATIVE_SESSION_PATH", native):
                with self.assertRaisesRegex(ValueError, "native acceptance source is missing"):
                    register_builder.functional_pilot(surface, by_path)

        stale_surface = json.loads(json.dumps(surface))
        next(
            item for item in stale_surface["public_commands"]
            if item["id"] == "cgate:SESSION_ID"
        )["source"]["syntax_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "public-help anchor is missing or stale"):
            register_builder.functional_pilot(stale_surface, by_path)
        missing_surface = json.loads(json.dumps(surface))
        missing_surface["public_commands"] = [
            item for item in missing_surface["public_commands"]
            if item["id"] != "cgate:SESSION_ID"
        ]
        with self.assertRaisesRegex(ValueError, "public-help anchor is missing or stale"):
            register_builder.functional_pilot(missing_surface, by_path)

        stale_contracts = json.loads(json.dumps(by_path))
        stale_contracts["SESSION_ID"]["contract_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "C-Gate contract anchor is missing or stale"):
            register_builder.functional_pilot(surface, stale_contracts)

        with TemporaryDirectory() as folder:
            native = json.loads(register_builder.NATIVE_SESSION_PATH.read_text())
            native["cases"] = [
                case for case in native["cases"]
                if case["command"] != "SESSION_ID bogus"
            ]
            native_path = Path(folder, "native.json")
            native_path.write_text(json.dumps(native))
            manifest = json.loads(register_builder.FUNCTIONAL_PILOT_PATH.read_text())
            manifest["native_oracle"]["sha256"] = sha256(native_path.read_bytes()).hexdigest()
            manifest_path = Path(folder, "pilot.json")
            manifest_path.write_text(json.dumps(manifest))
            with patch.object(register_builder, "NATIVE_SESSION_PATH", native_path), patch.object(
                register_builder, "FUNCTIONAL_PILOT_PATH", manifest_path
            ):
                with self.assertRaisesRegex(ValueError, "native case anchor is missing or stale"):
                    register_builder.functional_pilot(surface, by_path)

    def test_cgate_paths_have_independent_source_bound_obligations(self):
        register, _, _, _, contracts, _, _ = packaged_documents()
        obligations = {
            item["id"]: item
            for item in register["obligations"]
            if item.get("kind") == "cgate_path"
        }
        self.assertEqual(len(obligations), 442)
        self.assertEqual(
            {item["implementation_status"] for item in obligations.values()},
            {"in_progress"},
        )
        for contract in contracts["contracts"]:
            with self.subTest(path=contract["path"]):
                obligation_id = parity.cgate_path_obligation_id(contract["path"])
                obligation = obligations[obligation_id]
                self.assertEqual(obligation["contract_id"], contract["id"])
                self.assertEqual(obligation["contract_sha256"], contract["contract_sha256"])
                self.assertEqual(obligation["ledger_id"], "cgate-command-transport")
                self.assertEqual(obligation["definition_status"], "provisional")
                self.assertEqual(obligation["applicability_status"], "unresolved")
                self.assertEqual(obligation["acceptance"]["original_differential"], "unassessed")
                self.assertEqual(obligation["acceptance"]["physical"], "unassessed")
                self.assertIn("P0.03", obligation["work_item_ids"])

    def test_cgate_path_mapping_rejects_missing_duplicate_and_orphaned_rows(self):
        def first_path(register):
            return next(
                item for item in register["scope_items"]
                if item["kind"] == "cgate_primary_path"
            )

        register, *_ = packaged_documents()
        scope = first_path(register)
        scope["obligation_ids"].remove(parity.cgate_path_obligation_id(scope["source_id"]))
        with self.assertRaisesRegex(ValueError, "requires exactly its own C-Gate path obligation"):
            evaluate_packaged_change(register)

        register, *_ = packaged_documents()
        scope = first_path(register)
        specific_id = parity.cgate_path_obligation_id(scope["source_id"])
        register["obligations"] = [
            item for item in register["obligations"] if item["id"] != specific_id
        ]
        with self.assertRaisesRegex(ValueError, "names an unknown obligation"):
            evaluate_packaged_change(register)

        register, *_ = packaged_documents()
        register["obligations"].append(
            next(item for item in register["obligations"] if item.get("kind") == "cgate_path").copy()
        )
        with self.assertRaisesRegex(ValueError, "Duplicate obligation id"):
            evaluate_packaged_change(register)

        register, *_ = packaged_documents()
        invented_path = "INVENTED SUBCOMMAND"
        orphan = next(item for item in register["obligations"] if item.get("kind") == "cgate_path").copy()
        orphan["id"] = parity.cgate_path_obligation_id(invented_path)
        orphan["source_id"] = invented_path
        orphan["contract_id"] = f"cgate-contract:{orphan['id'].removeprefix('cgate-path:')}"
        register["obligations"].append(orphan)
        with self.assertRaisesRegex(ValueError, "path obligations differ from packaged contracts"):
            evaluate_packaged_change(register)

    def test_cgate_path_ledger_contract_and_route_only_claims_are_guarded(self):
        register, *_ = packaged_documents()
        obligation = next(item for item in register["obligations"] if item.get("kind") == "cgate_path")
        obligation["ledger_id"] = "toolkit-surface-census"
        with self.assertRaisesRegex(ValueError, "incorrect broad-ledger mapping"):
            evaluate_packaged_change(register)

        register, *_ = packaged_documents()
        obligation = next(item for item in register["obligations"] if item.get("kind") == "cgate_path")
        obligation["contract_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "differs from its source-bound C-Gate scope"):
            evaluate_packaged_change(register)

        register, *_ = packaged_documents()
        obligation = next(item for item in register["obligations"] if item.get("kind") == "cgate_path")
        obligation["implementation_status"] = "implemented"
        with self.assertRaisesRegex(ValueError, "overstates route-only implementation"):
            evaluate_packaged_change(register)

    def test_packaged_register_rejects_a_substituted_feature_ledger(self):
        ledger = json.loads((ROOT / "src/cbus_toolkit/capabilities.json").read_text())
        ledger["features"][0]["status"] = "pending"
        with self.assertRaisesRegex(ValueError, "differs from packaged"):
            parity.evaluate_packaged(ledger)

    def test_cgate_contract_domain_cannot_resolve_with_partial_axes(self):
        register, evidence, evidence_raw, contracts, contract_raw = (
            parity.load_packaged_documents()
        )
        ledger_raw = (ROOT / "src/cbus_toolkit/capabilities.json").read_bytes()
        ledger = parity.parse_json_document(ledger_raw, context="capabilities.json")
        domain = next(
            item
            for item in register["source_inventory"]
            if item["id"] == "cgate_selector_state_effect_contracts"
        )
        domain["resolved"] = True
        with self.assertRaisesRegex(ValueError, "contract axes remain partial or unresolved"):
            parity.validate_register(
                register,
                evidence,
                ledger,
                evidence_raw=evidence_raw,
                ledger_raw=ledger_raw,
                cgate_contract_inventory=contracts,
                cgate_contract_raw=contract_raw,
            )

    def test_feature_ledger_bytes_are_strictly_parsed_and_digest_bound(self):
        register, evidence, ledger, evidence_raw = fixture_documents()
        ledger_raw = (json.dumps(ledger, indent=2) + "\n").encode()
        register["source_digests"]["feature_ledger"] = sha256(ledger_raw).hexdigest()
        self.assertTrue(
            parity.evaluate(
                register,
                evidence,
                ledger,
                evidence_raw=evidence_raw,
                ledger_raw=ledger_raw,
                artifact_root=self.artifact_root,
            )["complete"]
        )
        changed = ledger_raw.replace(b'"fixture"', b'"changed"')
        with self.assertRaisesRegex(ValueError, "differs from supplied ledger"):
            parity.evaluate(
                register,
                evidence,
                ledger,
                evidence_raw=evidence_raw,
                ledger_raw=changed,
            )

    def test_evidence_bytes_are_strictly_parsed_and_content_bound(self):
        register, evidence, ledger, evidence_raw = fixture_documents()
        self.assertTrue(
            parity.evaluate(
                register, evidence, ledger, evidence_raw=evidence_raw,
                artifact_root=self.artifact_root,
            )["complete"]
        )

        substituted_evidence = json.loads(json.dumps(evidence))
        substituted_evidence["ignored_but_unbound"] = True
        with self.assertRaisesRegex(
            ValueError, "Parsed parity evidence differs from supplied evidence"
        ):
            parity.evaluate(
                register,
                substituted_evidence,
                ledger,
                evidence_raw=evidence_raw,
            )

        duplicate_raw = evidence_raw.replace(
            b'"schema_version": 1,',
            b'"schema_version": 1,\n  "schema_version": 1,',
            1,
        )
        register["evidence_bundle_sha256"] = sha256(duplicate_raw).hexdigest()
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            parity.evaluate(
                register, evidence, ledger, evidence_raw=duplicate_raw
            )

        nonfinite_raw = (
            evidence_raw.rstrip()[:-1] + b',\n  "ignored": NaN\n}\n'
        )
        register["evidence_bundle_sha256"] = sha256(nonfinite_raw).hexdigest()
        with self.assertRaisesRegex(ValueError, "Non-finite JSON number"):
            parity.evaluate(
                register, evidence, ledger, evidence_raw=nonfinite_raw
            )

    def test_complete_fixture_is_derived_from_obligations_and_evidence(self):
        register, evidence, ledger, evidence_raw = fixture_documents()
        with self.subTest("without source artifact verification"):
            report = parity.evaluate(
                register, evidence, ledger, evidence_raw=evidence_raw
            )
            self.assertFalse(report["complete"])
            self.assertFalse(report["evidence_artifacts_verified"])
            self.assertIsNone(report["obligations"]["accepted_percent"])
            self.assertEqual(
                report["acceptance_by_dimension"]["original_differential"]["percent"],
                None,
            )
            self.assertIsNone(report["physical_acceptance"]["percent"])
            self.assertIn(
                "evidence artifacts have not been verified against a trusted root",
                report["blockers"],
            )
        with self.subTest("with source artifact verification"):
            import tempfile

            with tempfile.TemporaryDirectory() as folder:
                Path(folder, "oracle.txt").write_bytes(b"fixture original")
                Path(folder, "result.txt").write_bytes(FIXTURE_REPORT)
                report = parity.evaluate(
                    register,
                    evidence,
                    ledger,
                    evidence_raw=evidence_raw,
                    artifact_root=Path(folder),
                )
                self.assertTrue(report["complete"])
                self.assertTrue(report["evidence_artifacts_verified"])

    def test_duplicate_json_keys_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            parity.parse_json_document('{"schema_version":1,"schema_version":1}', context="fixture")
        with self.assertRaisesRegex(ValueError, "Non-finite JSON number"):
            parity.parse_json_document('{"value":NaN}', context="fixture")
        with self.assertRaisesRegex(ValueError, "Non-finite JSON number"):
            parity.parse_json_document('{"value":1e400}', context="fixture")

    def test_missing_duplicate_and_unknown_ids_are_rejected(self):
        register, evidence, ledger, evidence_raw = fixture_documents()
        cases = []
        duplicate_obligation = json.loads(json.dumps(register))
        duplicate_obligation["obligations"].append(
            json.loads(json.dumps(duplicate_obligation["obligations"][0]))
        )
        cases.append((duplicate_obligation, evidence, "Duplicate obligation id"))
        missing_evidence = json.loads(json.dumps(register))
        missing_evidence["obligations"][0]["evidence_ids"] = ["evidence:missing"]
        cases.append((missing_evidence, evidence, "unknown evidence"))
        unknown_state = json.loads(json.dumps(register))
        unknown_state["obligations"][0]["acceptance"]["nominal"] = "maybe"
        cases.append((unknown_state, evidence, "unknown state"))
        for changed_register, changed_evidence, expected in cases:
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(ValueError, expected):
                    parity.evaluate(
                        changed_register,
                        changed_evidence,
                        ledger,
                        evidence_raw=evidence_raw,
                    )

    def test_work_items_must_belong_to_the_authoritative_roster(self):
        register, evidence, ledger, evidence_raw = fixture_documents()
        register["obligations"][0]["work_item_ids"] = ["P0.99"]
        with self.assertRaisesRegex(ValueError, "names unknown work items"):
            parity.evaluate(
                register, evidence, ledger, evidence_raw=evidence_raw
            )

        register, evidence, ledger, evidence_raw = fixture_documents()
        register["work_item_ids"].append("P0.99")
        with self.assertRaisesRegex(ValueError, "authoritative roster"):
            parity.evaluate(
                register, evidence, ledger, evidence_raw=evidence_raw
            )

    def test_nonfunctional_scope_requires_an_exact_passed_disposition_receipt(self):
        def exclusion_fixture() -> tuple[dict, dict, dict, bytes]:
            register, evidence, ledger, _ = fixture_documents()
            scope_item = register["scope_items"][0]
            scope_item["disposition"] = "nonfunctional_with_evidence"
            scope_item["obligation_ids"] = []
            scope_item["evidence_ids"] = ["evidence:one"]
            evidence_record = evidence["records"][0]
            evidence_record["scope_disposition_receipts"] = [
                {
                    "scope_item_id": "scope:one",
                    "decision": parity.SCOPE_EXCLUSION_DECISION,
                }
            ]
            write_fixture_report(evidence_record, self.artifact_root)
            raw = (json.dumps(evidence, indent=2) + "\n").encode()
            register["evidence_bundle_sha256"] = sha256(raw).hexdigest()
            return register, evidence, ledger, raw

        register, evidence, ledger, evidence_raw = exclusion_fixture()
        self.assertTrue(
            parity.evaluate(
                register, evidence, ledger, evidence_raw=evidence_raw,
                artifact_root=self.artifact_root,
            )["complete"]
        )

        register, evidence, ledger, _ = exclusion_fixture()
        evidence["records"][0]["scope_disposition_receipts"] = []
        evidence["records"][0]["record_sha256"] = record_digest(
            evidence["records"][0]
        )
        evidence_raw = (json.dumps(evidence, indent=2) + "\n").encode()
        register["evidence_bundle_sha256"] = sha256(evidence_raw).hexdigest()
        with self.assertRaisesRegex(ValueError, "lacks matching passed evidence"):
            parity.evaluate(
                register, evidence, ledger, evidence_raw=evidence_raw
            )

        register, evidence, ledger, _ = exclusion_fixture()
        evidence["records"][0]["scope_disposition_receipts"][0][
            "scope_item_id"
        ] = "scope:unrelated"
        evidence["records"][0]["record_sha256"] = record_digest(
            evidence["records"][0]
        )
        evidence_raw = (json.dumps(evidence, indent=2) + "\n").encode()
        register["evidence_bundle_sha256"] = sha256(evidence_raw).hexdigest()
        with self.assertRaisesRegex(ValueError, "lacks matching passed evidence"):
            parity.evaluate(
                register, evidence, ledger, evidence_raw=evidence_raw
            )

        register, evidence, ledger, _ = exclusion_fixture()
        evidence["records"][0]["result"] = "failed"
        evidence["records"][0]["exit_code"] = 1
        evidence["records"][0]["record_sha256"] = record_digest(
            evidence["records"][0]
        )
        register["obligations"][0]["acceptance"] = {
            dimension: "blocked" for dimension in parity.REQUIRED_DIMENSIONS
        }
        evidence_raw = (json.dumps(evidence, indent=2) + "\n").encode()
        register["evidence_bundle_sha256"] = sha256(evidence_raw).hexdigest()
        with self.assertRaisesRegex(ValueError, "lacks matching passed evidence"):
            parity.evaluate(
                register, evidence, ledger, evidence_raw=evidence_raw
            )

    def test_scope_disposition_receipts_are_strict_and_reciprocal(self):
        register, evidence, ledger, _ = fixture_documents()
        evidence_record = evidence["records"][0]
        evidence_record["scope_disposition_receipts"] = [
            {
                "scope_item_id": "scope:one",
                "decision": "an_unrecognized_decision",
            }
        ]
        evidence_record["record_sha256"] = record_digest(evidence_record)
        evidence_raw = (json.dumps(evidence, indent=2) + "\n").encode()
        register["evidence_bundle_sha256"] = sha256(evidence_raw).hexdigest()
        with self.assertRaisesRegex(ValueError, "unknown exclusion decision"):
            parity.evaluate(
                register, evidence, ledger, evidence_raw=evidence_raw
            )

        register, evidence, ledger, _ = fixture_documents()
        evidence_record = evidence["records"][0]
        receipt = {
            "scope_item_id": "scope:one",
            "decision": parity.SCOPE_EXCLUSION_DECISION,
        }
        evidence_record["scope_disposition_receipts"] = [receipt, dict(receipt)]
        evidence_record["record_sha256"] = record_digest(evidence_record)
        evidence_raw = (json.dumps(evidence, indent=2) + "\n").encode()
        register["evidence_bundle_sha256"] = sha256(evidence_raw).hexdigest()
        with self.assertRaisesRegex(ValueError, "duplicate scope disposition"):
            parity.evaluate(
                register, evidence, ledger, evidence_raw=evidence_raw
            )

        register, evidence, ledger, _ = fixture_documents()
        evidence_record = evidence["records"][0]
        evidence_record["scope_disposition_receipts"] = [receipt]
        evidence_record["record_sha256"] = record_digest(evidence_record)
        evidence_raw = (json.dumps(evidence, indent=2) + "\n").encode()
        register["evidence_bundle_sha256"] = sha256(evidence_raw).hexdigest()
        with self.assertRaisesRegex(ValueError, "does not match.*disposition"):
            parity.evaluate(
                register, evidence, ledger, evidence_raw=evidence_raw
            )

    def test_altered_bundle_record_and_artifact_are_rejected(self):
        register, evidence, ledger, evidence_raw = fixture_documents()
        altered_bundle = json.loads(json.dumps(evidence))
        altered_bundle["records"][0]["command"] += " -q"
        altered_raw = (json.dumps(altered_bundle, indent=2) + "\n").encode()
        with self.assertRaisesRegex(ValueError, "bundle digest changed"):
            parity.evaluate(
                register, altered_bundle, ledger, evidence_raw=altered_raw
            )
        register["evidence_bundle_sha256"] = sha256(altered_raw).hexdigest()
        with self.assertRaisesRegex(ValueError, "record digest changed"):
            parity.evaluate(
                register, altered_bundle, ledger, evidence_raw=altered_raw
            )

        register, evidence, ledger, evidence_raw = fixture_documents()
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "oracle.txt").write_bytes(b"fixture original")
            Path(folder, "result.txt").write_bytes(b"different\n")
            with self.assertRaisesRegex(ValueError, "artifact digest changed"):
                parity.evaluate(
                    register,
                    evidence,
                    ledger,
                    evidence_raw=evidence_raw,
                    artifact_root=Path(folder),
                )

    def test_rehashed_report_cannot_relabel_failed_or_uncovered_cases(self):
        alterations = {
            "failed case": lambda report: report["cases"][0].update(result="failed"),
            "uncovered dimension": lambda report: report["cases"][0]["dimensions"].remove("physical"),
            "different test": lambda report: report["cases"][0].update(id="tests/other.py::test_other"),
            "different revision": lambda report: report.update(source_revision="2" * 40),
        }
        for label, alter in alterations.items():
            with self.subTest(label=label), TemporaryDirectory() as folder:
                register, evidence, ledger, _ = fixture_documents()
                report = json.loads(FIXTURE_REPORT)
                alter(report)
                report_raw = (json.dumps(report, sort_keys=True) + "\n").encode()
                root = Path(folder)
                (root / "oracle.txt").write_bytes(b"fixture original")
                (root / "result.txt").write_bytes(report_raw)
                record = evidence["records"][0]
                record["artifacts"][1]["sha256"] = sha256(report_raw).hexdigest()
                record["record_sha256"] = record_digest(record)
                evidence_raw = (json.dumps(evidence, indent=2) + "\n").encode()
                register["evidence_bundle_sha256"] = sha256(evidence_raw).hexdigest()
                with self.assertRaisesRegex(ValueError, "report .*|report cases"):
                    parity.evaluate(
                        register, evidence, ledger,
                        evidence_raw=evidence_raw, artifact_root=root,
                    )

    def test_rehashed_session_differential_cannot_claim_mismatched_payload(self):
        _, evidence, _, _, _, _, _ = packaged_documents()
        record = evidence["records"][0]
        report_source = ROOT / "research/fixtures/cgate-session-differential-cmqttd.json"
        report_relative = "research/fixtures/cgate-session-differential-cmqttd.json"
        record["report_verification"] = {
            "format": "cgate-session-differential-v2",
            "path": report_relative,
        }
        record["record_sha256"] = record_digest(record)
        parity.validate_evidence_bundle(evidence, artifact_root=ROOT)

        alterations = {
            "normalized payload": lambda report: report["cases"][0].update(
                rust_normalized=["300 sessionID=substituted"]
            ),
            "raw wire": lambda report: report["cases"][0].update(
                rust_wire_reply=["[d00] 300 sessionID=cmd3\n"]
            ),
            "missing case": lambda report: report["cases"].pop(),
        }
        for label, alter in alterations.items():
            with self.subTest(label=label), TemporaryDirectory() as folder:
                current = json.loads(json.dumps(evidence))
                current_record = current["records"][0]
                root = Path(folder)
                for artifact in current_record["artifacts"]:
                    destination = root / artifact["path"]
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes((ROOT / artifact["path"]).read_bytes())
                report = json.loads(report_source.read_bytes())
                alter(report)
                report_raw = (json.dumps(report, indent=2) + "\n").encode()
                (root / report_relative).write_bytes(report_raw)
                next(artifact for artifact in current_record["artifacts"]
                     if artifact["path"] == report_relative)["sha256"] = sha256(report_raw).hexdigest()
                current_record["record_sha256"] = record_digest(current_record)
                with self.assertRaisesRegex(ValueError, "differential (case evidence changed|report is incomplete)"):
                    parity.validate_evidence_bundle(current, artifact_root=root)

    def test_passed_evidence_requires_a_recognized_report_artifact(self):
        register, evidence, ledger, _ = fixture_documents()
        record = evidence["records"][0]
        record.pop("report_verification")
        record["record_sha256"] = record_digest(record)
        evidence_raw = (json.dumps(evidence, indent=2) + "\n").encode()
        register["evidence_bundle_sha256"] = sha256(evidence_raw).hexdigest()
        with self.assertRaisesRegex(ValueError, "requires a recognized report artifact"):
            parity.evaluate(register, evidence, ledger, evidence_raw=evidence_raw)

    def test_rehashed_decision_declarations_must_match_executed_report(self):
        decisions = {
            "applicability_receipts": [{
                "obligation_id": "obligation:one",
                "dimension": "physical",
                "decision": "not_applicable",
                "reason": "Static fixture has no bus output",
            }],
            "scope_disposition_receipts": [{
                "scope_item_id": "scope:one",
                "decision": parity.SCOPE_EXCLUSION_DECISION,
            }],
        }
        for field, receipts in decisions.items():
            with self.subTest(field=field):
                _, evidence, _, _ = fixture_documents()
                record = evidence["records"][0]
                record[field] = json.loads(json.dumps(receipts))
                write_fixture_report(record, self.artifact_root)
                if field == "applicability_receipts":
                    record[field][0]["reason"] = "Different unsupported claim"
                else:
                    record[field][0]["scope_item_id"] = "scope:other"
                record["record_sha256"] = record_digest(record)
                with self.assertRaisesRegex(ValueError, "report decisions differ"):
                    parity.validate_evidence_bundle(
                        evidence, artifact_root=self.artifact_root
                    )

    def test_passed_evidence_requires_result_and_bound_oracle_artifacts(self):
        def changed_case(mutate, expected):
            register, evidence, ledger, _ = fixture_documents()
            record = evidence["records"][0]
            mutate(record)
            record["record_sha256"] = record_digest(record)
            raw = (json.dumps(evidence, indent=2) + "\n").encode()
            register["evidence_bundle_sha256"] = sha256(raw).hexdigest()
            with self.assertRaisesRegex(ValueError, expected):
                parity.evaluate(register, evidence, ledger, evidence_raw=raw)

        changed_case(
            lambda record: record["artifacts"].pop(),
            "passed evidence requires an output or report artifact",
        )
        changed_case(
            lambda record: record["oracle"].update(
                artifact_sha256=sha256(b"unrelated oracle").hexdigest()
            ),
            "oracle digest requires a matching input artifact",
        )
        changed_case(
            lambda record: record["artifacts"][0].update(
                sha256=sha256(b"unrelated input").hexdigest()
            ),
            "oracle digest requires a matching input artifact",
        )

    def test_skipped_cases_cannot_be_duplicated_or_claimed_executed(self):
        def changed_case(skips, expected):
            register, evidence, ledger, _ = fixture_documents()
            record = evidence["records"][0]
            record["skips"] = skips
            record["record_sha256"] = record_digest(record)
            raw = (json.dumps(evidence, indent=2) + "\n").encode()
            register["evidence_bundle_sha256"] = sha256(raw).hexdigest()
            with self.assertRaisesRegex(ValueError, expected):
                parity.evaluate(register, evidence, ledger, evidence_raw=raw)

        optional = {"case_id": "optional", "reason": "fixture unavailable", "required": False}
        changed_case([optional, dict(optional)], "duplicate skipped case IDs")
        changed_case(
            [{**optional, "case_id": "tests/test_one.py::test_one"}],
            "claims a skipped test as executed",
        )

    def test_required_and_unexplained_skips_are_rejected(self):
        register, evidence, ledger, _ = fixture_documents()
        for skip, expected in (
            ({"case_id": "hardware", "reason": "missing", "required": True}, "required skipped"),
            ({"case_id": "hardware", "reason": "", "required": False}, "without reason"),
        ):
            changed = json.loads(json.dumps(evidence))
            changed["records"][0]["skips"] = [skip]
            changed["records"][0]["record_sha256"] = record_digest(changed["records"][0])
            raw = (json.dumps(changed, indent=2) + "\n").encode()
            changed_register = json.loads(json.dumps(register))
            changed_register["evidence_bundle_sha256"] = sha256(raw).hexdigest()
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(ValueError, expected):
                    parity.evaluate(
                        changed_register, changed, ledger, evidence_raw=raw
                    )

    def test_not_applicable_dimension_requires_matching_passed_decision(self):
        register, evidence, ledger, evidence_raw = fixture_documents()
        register["obligations"][0]["acceptance"]["physical"] = "not_applicable"
        evidence["records"][0]["dimensions"].remove("physical")
        evidence["records"][0]["record_sha256"] = record_digest(evidence["records"][0])
        evidence_raw = (json.dumps(evidence, indent=2) + "\n").encode()
        register["evidence_bundle_sha256"] = sha256(evidence_raw).hexdigest()
        with self.assertRaisesRegex(ValueError, "lacks a passed not-applicable decision"):
            parity.evaluate(register, evidence, ledger, evidence_raw=evidence_raw)

    def test_not_applicable_requires_explicit_hash_bound_decision(self):
        register, evidence, ledger, _ = fixture_documents()
        register["obligations"][0]["acceptance"]["physical"] = "not_applicable"

        def evaluate_current():
            record = evidence["records"][0]
            write_fixture_report(record, self.artifact_root)
            raw = (json.dumps(evidence, indent=2) + "\n").encode()
            register["evidence_bundle_sha256"] = sha256(raw).hexdigest()
            return parity.evaluate(
                register, evidence, ledger, evidence_raw=raw,
                artifact_root=self.artifact_root,
            )

        # A passed physical test is not a reason to remove a physical test
        # obligation from the denominator.
        with self.assertRaisesRegex(ValueError, "lacks a passed not-applicable decision"):
            evaluate_current()

        receipt = {
            "obligation_id": "obligation:one",
            "dimension": "physical",
            "decision": "not_applicable",
            "reason": "This fixture outcome has no physical side effect",
        }
        evidence["records"][0]["applicability_receipts"] = [receipt]
        self.assertTrue(evaluate_current()["complete"])

        for changed, expected in (
            ({**receipt, "reason": " "}, "requires a reason"),
            ({**receipt, "dimension": "error"}, "lacks a passed not-applicable decision"),
            ({**receipt, "dimension": ["physical"]}, "not bound to this evidence"),
            ({**receipt, "obligation_id": "unrelated"}, "not bound to this evidence"),
            ({**receipt, "decision": "accepted"}, "unknown applicability decision"),
        ):
            evidence["records"][0]["applicability_receipts"] = [changed]
            with self.subTest(expected=expected), self.assertRaisesRegex(ValueError, expected):
                evaluate_current()

        evidence["records"][0]["applicability_receipts"] = [receipt, dict(receipt)]
        with self.assertRaisesRegex(ValueError, "duplicate applicability receipts"):
            evaluate_current()

        evidence["records"][0]["applicability_receipts"] = [receipt]
        register["obligations"][0]["acceptance"]["physical"] = "accepted"
        with self.assertRaisesRegex(ValueError, "applicability receipt differs"):
            evaluate_current()

    def test_offline_decision_only_receipt_can_exclude_physical_and_original(self):
        register, evidence, ledger, _ = fixture_documents()
        obligation = register["obligations"][0]
        for dimension in ("physical", "original_differential"):
            obligation["acceptance"][dimension] = "not_applicable"
        exercised = evidence["records"][0]
        exercised["dimensions"] = [
            dimension for dimension in exercised["dimensions"]
            if dimension not in {"physical", "original_differential"}
        ]
        exercised["environment"] = {"kind": "offline", "identity": "fixture process"}
        del exercised["oracle"]
        write_fixture_report(exercised, self.artifact_root)

        decision = json.loads(json.dumps(exercised))
        decision["id"] = "evidence:applicability"
        decision["dimensions"] = []
        decision["test_ids"] = ["tests/test_applicability.py::test_no_physical_or_oracle"]
        decision["command"] = "python -m pytest tests/test_applicability.py"
        decision["report_verification"]["path"] = "decision.txt"
        next(artifact for artifact in decision["artifacts"] if artifact["role"] == "report")[
            "path"
        ] = "decision.txt"
        decision["applicability_receipts"] = [
            {
                "obligation_id": "obligation:one",
                "dimension": dimension,
                "decision": "not_applicable",
                "reason": f"Static analysis excludes {dimension} for this fixture",
            }
            for dimension in ("physical", "original_differential")
        ]
        write_fixture_report(decision, self.artifact_root)
        evidence["records"].append(decision)
        obligation["evidence_ids"].append(decision["id"])

        def evaluate_current():
            write_fixture_report(decision, self.artifact_root)
            raw = (json.dumps(evidence, indent=2) + "\n").encode()
            register["evidence_bundle_sha256"] = sha256(raw).hexdigest()
            return parity.evaluate(
                register, evidence, ledger, evidence_raw=raw,
                artifact_root=self.artifact_root,
            )

        self.assertTrue(evaluate_current()["complete"])
        decision["result"] = "failed"
        decision["exit_code"] = 1
        with self.assertRaisesRegex(ValueError, "lacks a passed not-applicable decision"):
            evaluate_current()
        decision["result"] = "skipped"
        with self.assertRaisesRegex(ValueError, "lacks a passed not-applicable decision"):
            evaluate_current()
        decision["result"] = "passed"
        decision["exit_code"] = 0
        decision["applicability_receipts"].pop()
        with self.assertRaisesRegex(ValueError, "original_differential lacks a passed not-applicable decision"):
            evaluate_current()
        decision["applicability_receipts"] = []
        with self.assertRaisesRegex(ValueError, "has no dimension or decision to evidence"):
            evaluate_current()

    def test_sensitive_evidence_requires_physical_environment_and_original_oracle(self):
        register, evidence, ledger, _ = fixture_documents()
        cases = []
        offline = json.loads(json.dumps(evidence))
        offline["records"][0]["environment"] = {
            "kind": "offline",
            "identity": "local fixture",
        }
        cases.append((offline, "physical evidence requires a physical environment"))
        no_oracle = json.loads(json.dumps(evidence))
        del no_oracle["records"][0]["oracle"]
        cases.append((no_oracle, "differential evidence requires an oracle"))
        nonzero_pass = json.loads(json.dumps(evidence))
        nonzero_pass["records"][0]["exit_code"] = 1
        cases.append((nonzero_pass, "passed evidence requires exit_code 0"))
        malformed_result = json.loads(json.dumps(evidence))
        malformed_result["records"][0]["result"] = []
        cases.append((malformed_result, "unknown result"))
        malformed_environment = json.loads(json.dumps(evidence))
        malformed_environment["records"][0]["environment"]["kind"] = []
        cases.append((malformed_environment, "unknown environment kind"))
        for changed, expected in cases:
            changed["records"][0]["record_sha256"] = record_digest(
                changed["records"][0]
            )
            raw = (json.dumps(changed, indent=2) + "\n").encode()
            changed_register = json.loads(json.dumps(register))
            changed_register["evidence_bundle_sha256"] = sha256(raw).hexdigest()
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(ValueError, expected):
                    parity.evaluate(
                        changed_register, changed, ledger, evidence_raw=raw
                    )

    def test_evidence_target_and_obligation_references_must_match(self):
        register, evidence, ledger, _ = fixture_documents()
        evidence["target"] = "different target"
        raw = (json.dumps(evidence, indent=2) + "\n").encode()
        register["evidence_bundle_sha256"] = sha256(raw).hexdigest()
        with self.assertRaisesRegex(ValueError, "target does not match"):
            parity.evaluate(register, evidence, ledger, evidence_raw=raw)

        register, evidence, ledger, _ = fixture_documents()
        evidence["records"][0]["obligation_ids"] = [
            "obligation:one",
            "obligation:unknown",
        ]
        evidence["records"][0]["record_sha256"] = record_digest(
            evidence["records"][0]
        )
        raw = (json.dumps(evidence, indent=2) + "\n").encode()
        register["evidence_bundle_sha256"] = sha256(raw).hexdigest()
        with self.assertRaisesRegex(ValueError, "unknown obligations"):
            parity.evaluate(register, evidence, ledger, evidence_raw=raw)

    def test_census_complete_cannot_hide_unresolved_scope(self):
        register, evidence, ledger, evidence_raw = fixture_documents()
        register["scope_items"][0]["disposition"] = "pending_analysis"
        with self.assertRaisesRegex(ValueError, "cannot hide unresolved scope"):
            parity.evaluate(register, evidence, ledger, evidence_raw=evidence_raw)

    def test_resolved_domains_and_scope_items_cannot_hide_unknown_work(self):
        register, evidence, ledger, evidence_raw = fixture_documents()
        register["source_inventory"][0]["count"] = None
        with self.assertRaisesRegex(ValueError, "resolved with an unknown count"):
            parity.evaluate(register, evidence, ledger, evidence_raw=evidence_raw)

        register, evidence, ledger, evidence_raw = fixture_documents()
        register["scope_items"][0]["obligation_ids"] = []
        with self.assertRaisesRegex(ValueError, "no mapped obligation"):
            parity.evaluate(register, evidence, ledger, evidence_raw=evidence_raw)

    def test_complete_census_requires_one_counted_domain_per_scope_kind(self):
        register, evidence, ledger, evidence_raw = fixture_documents()
        self.assertTrue(
            parity.evaluate(
                register, evidence, ledger, evidence_raw=evidence_raw,
                artifact_root=self.artifact_root,
            )[
                "complete"
            ]
        )

        # Previously this still returned complete=true: the one functional
        # scope item was no longer represented by a counted source domain.
        register["source_inventory"][0].update(
            {"scope_kind": "unrelated", "count": 0}
        )
        with self.assertRaisesRegex(
            ValueError, r"scope kinds differ.*missing=\['fixture'\]"
        ):
            parity.evaluate(register, evidence, ledger, evidence_raw=evidence_raw)

        register, evidence, ledger, evidence_raw = fixture_documents()
        del register["source_inventory"][0]["scope_kind"]
        with self.assertRaisesRegex(ValueError, "scope kinds differ"):
            parity.evaluate(register, evidence, ledger, evidence_raw=evidence_raw)

        register, evidence, ledger, evidence_raw = fixture_documents()
        register["source_inventory"].append(
            {"id": "duplicate", "scope_kind": "fixture", "count": 1, "resolved": True}
        )
        with self.assertRaisesRegex(ValueError, "Duplicate source inventory scope kind"):
            parity.evaluate(register, evidence, ledger, evidence_raw=evidence_raw)

        register, evidence, ledger, evidence_raw = fixture_documents()
        register["source_inventory"][0]["scope_kind"] = ""
        with self.assertRaisesRegex(ValueError, "scope_kind must be a nonempty string"):
            parity.evaluate(register, evidence, ledger, evidence_raw=evidence_raw)


if __name__ == "__main__":
    unittest.main()
