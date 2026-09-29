"""Phase 4: coverage gate must stay honest/red (TDD).

Proves ``cbus-toolkit coverage --require-complete`` still exits nonzero
while the ledger is incomplete. This guards against status inflation:
``census_complete`` stays false and unfinished ledger IDs remain until a
later phase supplies independent acceptance evidence.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest


class CoverageRequireCompleteTests(unittest.TestCase):
    def test_evidence_root_verifies_artifacts_without_claiming_full_parity(self):
        root = Path(__file__).resolve().parents[1]
        proc = subprocess.run(
            [sys.executable, "-m", "cbus_toolkit", "coverage",
             "--evidence-root", str(root), "--require-complete"],
            text=True, capture_output=True, timeout=120,
        )
        self.assertEqual(proc.returncode, 1, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["progress"]["evidence_artifacts_verified"])
        self.assertFalse(payload["progress"]["complete"])

        missing = subprocess.run(
            [sys.executable, "-m", "cbus_toolkit", "coverage",
             "--evidence-root", str(root / "missing-evidence-root")],
            text=True, capture_output=True, timeout=120,
        )
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("artifact is missing", missing.stdout + missing.stderr)

    def test_coverage_reports_blocked_hardware_separately(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbus_toolkit", "coverage"],
            text=True, capture_output=True, timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        progress = json.loads(proc.stdout)["progress"]
        physical = progress["physical_acceptance"]
        self.assertEqual(physical["blocked"], 263)
        self.assertEqual(physical["accepted"], 0)
        self.assertEqual(physical["not_applicable"], 3)
        self.assertEqual(
            physical["blocked"] + physical["unassessed"] + physical["accepted"],
            physical["required"],
        )
        self.assertEqual(physical["unavailable_fixtures"], progress["hardware_fixtures"]["total"])
        self.assertEqual(progress["hardware_fixtures"]["provisioned"], 0)
        self.assertEqual(progress["blocked_obligations"], 263)
        for dimension, counts in progress["acceptance_by_dimension"].items():
            with self.subTest(dimension=dimension):
                self.assertIn("blocked", counts)
        self.assertTrue(
            any("unavailable hardware fixtures" in item for item in progress["blockers"])
        )

    def test_blocked_dimension_never_satisfies_completion(self):
        from tempfile import TemporaryDirectory

        from cbus_toolkit import parity
        from test_parity_register import FIXTURE_REPORT, fixture_documents

        register, evidence, ledger, evidence_raw = fixture_documents()
        register["source_digests"]["hardware_fixture_matrix"] = "0" * 64
        register["hardware_fixture_roster"] = [
            {"id": "fixture:unit:DIMX", "family": "dimmer", "status": "unavailable"}
        ]
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "oracle.txt").write_bytes(b"fixture original")
            (root / "result.txt").write_bytes(FIXTURE_REPORT)
            complete = parity.evaluate(
                register, evidence, ledger, evidence_raw=evidence_raw, artifact_root=root
            )
            self.assertTrue(complete["complete"])
            obligation = register["obligations"][0]
            obligation["acceptance"]["physical"] = "blocked"
            obligation["acceptance_blockers"] = {
                "physical": {
                    "reason_kind": "hardware_fixture_unavailable",
                    "blocker_ids": ["fixture:unit:DIMX"],
                }
            }
            report = parity.evaluate(
                register, evidence, ledger, evidence_raw=evidence_raw, artifact_root=root
            )
        self.assertFalse(report["complete"])
        self.assertEqual(report["obligations"]["accepted"], 0)
        self.assertEqual(report["obligations"]["accepted_percent"], 0.0)
        physical = report["physical_acceptance"]
        self.assertEqual((physical["required"], physical["accepted"]), (1, 0))
        self.assertEqual((physical["blocked"], physical["not_applicable"]), (1, 0))
        self.assertEqual(physical["percent"], 0.0)

    def test_require_complete_still_fails(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbus_toolkit", "coverage", "--require-complete"],
            text=True,
            capture_output=True,
            timeout=120,
        )
        self.assertEqual(proc.returncode, 1, proc.stderr + proc.stdout)
        combined = (proc.stdout or "") + (proc.stderr or "")
        start = combined.find("{")
        end = combined.rfind("}")
        self.assertGreaterEqual(start, 0, combined)
        self.assertGreater(end, start, combined)
        payload = json.loads(combined[start : end + 1])
        self.assertFalse(payload["complete"])
        self.assertFalse(payload["census_complete"])
        progress = payload["progress"]
        self.assertFalse(progress["complete"])
        self.assertFalse(progress["denominator_ready"])
        self.assertFalse(progress["functional_percent_available"])
        self.assertFalse(progress["evidence_artifacts_verified"])
        self.assertIsNone(progress["obligations"]["implementation_percent"])
        self.assertIsNone(progress["obligations"]["accepted_percent"])
        self.assertEqual(progress["legacy_category_summary"]["implemented"], 18)
        self.assertEqual(
            progress["legacy_category_summary"]["implemented_percent"], 43.9
        )
        self.assertFalse(
            progress["legacy_category_summary"]["functionality_estimate"]
        )
        self.assertGreater(progress["scope_items"]["unresolved"], 0)
        self.assertEqual(len(payload["features"]), 41)
        self.assertTrue(
            any(feature["status"] != "implemented" for feature in payload["features"])
        )
        by_id = {feature["id"]: feature for feature in payload["features"]}
        for pending_id in (
            "toolkit-differential-acceptance",
            "unit-hardware-acceptance",
        ):
            with self.subTest(area=pending_id):
                self.assertIn(pending_id, by_id)
                self.assertEqual(by_id[pending_id]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
