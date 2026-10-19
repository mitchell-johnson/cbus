"""Offline P1.01-P1.05 pins: one small verifiable fact per issue 18-22.

#18 (P1.01): artifact manifest group count + DFU boundary doc statement.
#19 (P1.02): Windows native-oracle matrix row for the target Toolkit EXE.
#20 (P1.03): page-control workflow receipt identity and single-command invariant.
#21 (P1.04): hardware fixture matrix size, inputs and unavailable status.
#22 (P1.05): wheel-interop CI gate journey present in Makefile and ci.yml.
All checks are offline and read only committed files; provisioned gates stay open.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


class P1Issue18ArtifactHashDocTests(unittest.TestCase):
    def test_manifest_groups_and_doc_dfu_boundary(self):
        manifest = json.loads((ROOT / "research/original-artifact-provenance.json").read_text())
        self.assertEqual(len(manifest["artifacts"]), 25)
        self.assertEqual(manifest["specification_derivation"]["decoded_count"], 280)
        doc = (ROOT / "docs/original-artifact-provenance.md").read_text()
        self.assertIn("lmdfu_edlt.dll", doc)
        self.assertIn("dfu-acceptance-summary.json", doc)
        self.assertIn("no individual manifest records", doc)


class P1Issue19WindowsMatrixRowTests(unittest.TestCase):
    def test_windows_oracle_pins_target_toolkit_exe_row(self):
        doc = (ROOT / "docs/windows-native-oracle.md").read_text()
        self.assertIn("CBusToolkit.exe | 1.18.0.2754", doc)
        self.assertIn(
            "9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab",
            doc,
        )
        self.assertIn("CBusLogicModel.dll", doc)


class P1Issue20WorkflowReceiptTests(unittest.TestCase):
    def test_page_control_receipt_identity_and_first_open(self):
        receipt = json.loads(
            (ROOT / "research/fixtures/original-workflow-page-control-receipt.json").read_text()
        )
        self.assertEqual(receipt["format"], "cbus-original-workflow-receipt-v1")
        self.assertEqual(receipt["workflow"], "edlt-page-control-database-unit")
        self.assertEqual(receipt["group"], 42)
        self.assertTrue(receipt["passed"])
        first_open = receipt["cli_first_open"]
        self.assertEqual(first_open["parameter_differences_from_original"], [])
        self.assertEqual([s["command"] for s in first_open["steps"]], ["edlt-page-control"])


class P1Issue21DeviceMatrixEntryTests(unittest.TestCase):
    def test_hardware_matrix_size_inputs_and_status(self):
        matrix = json.loads((ROOT / "research/hardware-fixture-matrix.json").read_text())
        self.assertEqual(len(matrix["fixtures"]), 264)
        self.assertEqual(matrix["inputs"]["unit_spec_count"], 280)
        self.assertEqual(matrix["counts"]["by_status"], {"unavailable": 264})
        ids = {row["id"] for row in matrix["fixtures"]}
        self.assertIn("fixture:topology:bridges-6", ids)
        self.assertTrue(all(row["private_manifest_ref"] is None for row in matrix["fixtures"]))


class P1Issue22CIGateJourneyTests(unittest.TestCase):
    JOURNEY_MOCK = (
        "test_cgate_din_save_interop.py::"
        "test_public_din_successful_save_lost_response_is_not_replayed[DIMDN8-mock]"
    )
    JOURNEY_DAEMON = (
        "test_cgate_din_save_interop.py::"
        "test_public_din_successful_save_lost_response_is_not_replayed[DIMDN8-daemon]"
    )

    def test_wheel_interop_journey_pinned_in_makefile_and_ci(self):
        makefile = (ROOT / "Makefile").read_text()
        self.assertIn("check-wheel-interop", makefile)
        self.assertIn(self.JOURNEY_MOCK, makefile)
        self.assertIn(self.JOURNEY_DAEMON, makefile)
        ci = (REPO / ".github/workflows/ci.yml").read_text()
        self.assertIn("check-wheel-interop", ci)
        self.assertIn("tests/test_cgate_din_save_interop.py", ci)
        gate = json.loads((ROOT / "research/release-gates/native.json").read_text())
        self.assertEqual(gate["gate"], "native")


if __name__ == "__main__":
    unittest.main()
