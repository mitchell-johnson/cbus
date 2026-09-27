from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import unittest

from cbus_toolkit import parity


ROOT = Path(__file__).resolve().parents[1]


def record_digest(record: dict) -> str:
    content = {key: value for key, value in record.items() if key != "record_sha256"}
    return sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def fixture_documents() -> tuple[dict, dict, dict, bytes]:
    artifact = b"accepted result\n"
    evidence_record = {
        "id": "evidence:one",
        "obligation_ids": ["obligation:one"],
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
        "artifacts": [
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


class ParityRegisterTests(unittest.TestCase):
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
        self.assertEqual(report["obligations"]["total"], 39)
        self.assertEqual(report["obligations"]["defined"], 0)
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
        self.assertEqual(report["evidence_records"], 0)

    def test_packaged_register_rejects_a_substituted_feature_ledger(self):
        ledger = json.loads((ROOT / "src/cbus_toolkit/capabilities.json").read_text())
        ledger["features"][0]["status"] = "pending"
        with self.assertRaisesRegex(ValueError, "differs from packaged"):
            parity.evaluate_packaged(ledger)

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

    def test_complete_fixture_is_derived_from_obligations_and_evidence(self):
        register, evidence, ledger, evidence_raw = fixture_documents()
        with self.subTest("without source artifact verification"):
            report = parity.evaluate(
                register, evidence, ledger, evidence_raw=evidence_raw
            )
            self.assertTrue(report["complete"])
            self.assertEqual(report["obligations"]["accepted_percent"], 100.0)
            self.assertEqual(
                report["acceptance_by_dimension"]["original_differential"]["percent"],
                100.0,
            )
            self.assertEqual(report["physical_acceptance"]["percent"], 100.0)
        with self.subTest("with source artifact verification"):
            import tempfile

            with tempfile.TemporaryDirectory() as folder:
                Path(folder, "result.txt").write_bytes(b"accepted result\n")
                report = parity.evaluate(
                    register,
                    evidence,
                    ledger,
                    evidence_raw=evidence_raw,
                    artifact_root=Path(folder),
                )
                self.assertTrue(report["complete"])

    def test_duplicate_json_keys_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            parity.parse_json_document('{"schema_version":1,"schema_version":1}', context="fixture")
        with self.assertRaisesRegex(ValueError, "Non-finite JSON number"):
            parity.parse_json_document('{"value":NaN}', context="fixture")

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
            Path(folder, "result.txt").write_bytes(b"different\n")
            with self.assertRaisesRegex(ValueError, "artifact digest changed"):
                parity.evaluate(
                    register,
                    evidence,
                    ledger,
                    evidence_raw=evidence_raw,
                    artifact_root=Path(folder),
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

    def test_not_applicable_dimension_requires_matching_passed_evidence(self):
        register, evidence, ledger, evidence_raw = fixture_documents()
        register["obligations"][0]["acceptance"]["physical"] = "not_applicable"
        evidence["records"][0]["dimensions"].remove("physical")
        evidence["records"][0]["record_sha256"] = record_digest(evidence["records"][0])
        evidence_raw = (json.dumps(evidence, indent=2) + "\n").encode()
        register["evidence_bundle_sha256"] = sha256(evidence_raw).hexdigest()
        with self.assertRaisesRegex(ValueError, "lacks matching passed evidence"):
            parity.evaluate(register, evidence, ledger, evidence_raw=evidence_raw)

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


if __name__ == "__main__":
    unittest.main()
