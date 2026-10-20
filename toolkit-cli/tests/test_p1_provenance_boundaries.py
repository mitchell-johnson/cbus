"""P1 #18-#21 offline provenance boundaries: hash/pin cross-checks, no Windows/HW.

Every assertion reads only committed files. Nothing here requires private
vendor roots, a Windows guest, or physical hardware; provision-gated live
captures stay in their own suites. The point is to keep the documented
acceptance boundaries machine-checked so a stale doc or a silently dropped
pin cannot be mistaken for closure of #18/#19/#20/#21.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "research/original-artifact-provenance.json"
DFU_SUMMARY = ROOT / "docs/dfu-acceptance-summary.json"
PROVENANCE_DOC = ROOT / "docs/original-artifact-provenance.md"
ORACLE_DOC = ROOT / "docs/windows-native-oracle.md"
AUTHENTICODE = ROOT / "research/authenticode_check.py"
MATRIX = ROOT / "research/hardware-fixture-matrix.json"
PAGE_CONTROL_RECEIPT = ROOT / "research/fixtures/original-workflow-page-control-receipt.json"

HEX64 = re.compile(r"^[0-9a-f]{64}$")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class ProvenanceBoundaryTests(unittest.TestCase):
    def test_manifest_shape_and_no_individual_dfu_pin(self):
        manifest = load_json(MANIFEST)
        self.assertEqual(manifest["format"], "cbus-original-artifact-provenance-v1")
        self.assertEqual(manifest["target"], "Toolkit 1.18.0.2754 / C-Gate 3.4.0.2001")
        self.assertEqual(len(manifest["artifacts"]), 25)
        ids = [record["id"] for record in manifest["artifacts"]]
        self.assertIn("edlt-firmware", ids)
        dfu_pins = [ident for ident in ids if "dfu" in ident]
        self.assertEqual(dfu_pins, [],
                         "DFU binaries are tree-covered only; an individual pin needs repinning review")

    def test_dfu_binaries_located_with_hashes_but_outside_manifest(self):
        summary = load_json(DFU_SUMMARY)
        sources = summary["native_sources"]
        self.assertEqual(len(sources), 5)
        by_name = {Path(entry["path"]).name: entry for entry in sources}
        for name in ("dfuprog.exe", "lmdfu_edlt.dll", "lmdfu_edlt64.dll",
                     "lmusbdll.dll", "edlt_dfu.inf"):
            with self.subTest(name=name):
                self.assertIn(name, by_name)
                self.assertTrue(HEX64.match(by_name[name]["sha256"]), name)
        dll = next(entry for entry in sources if entry["path"].endswith("i386/lmdfu_edlt.dll"))
        self.assertIn("Firmware/eDLTFirmware/usb_drivers/i386/", dll["path"])
        manifest_ids = {record["id"] for record in load_json(MANIFEST)["artifacts"]}
        self.assertNotIn("dfu-dll", manifest_ids)

    def test_windows_oracle_doc_matches_manifest_toolkit_pin(self):
        manifest = load_json(MANIFEST)
        toolkit_exe = next(record for record in manifest["artifacts"] if record["id"] == "toolkit-exe")
        oracle_text = ORACLE_DOC.read_text(encoding="utf-8")
        self.assertIn(toolkit_exe["sha256"], oracle_text)
        self.assertIn("1.18.0.2754", oracle_text)

    def test_authenticode_checker_disclaims_windows_policy(self):
        source = AUTHENTICODE.read_text(encoding="utf-8")
        self.assertIn("not Windows policy", source)
        self.assertIn("signtool", source)
        self.assertIn("revocation", source)

    def test_provenance_doc_records_all_open_boundaries(self):
        text = PROVENANCE_DOC.read_text(encoding="utf-8")
        for marker in ("CBUS_DFU_DLL", "Windows", "signtool", "isolated Windows profiles",
                       "case-level original comparison receipts", "dfu-acceptance-summary.json"):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_hardware_matrix_unavailable_and_complete_offline(self):
        matrix = load_json(MATRIX)
        self.assertEqual(matrix["format"], "cbus-hardware-fixture-matrix-v1")
        self.assertEqual(matrix["counts"]["fixtures"], 264)
        self.assertEqual(len(matrix["fixtures"]), 264)
        self.assertEqual(matrix["counts"]["by_status"], {"unavailable": 264})
        self.assertTrue(all(row["status"] == "unavailable" for row in matrix["fixtures"]))
        self.assertTrue(all(row["private_manifest_ref"] is None for row in matrix["fixtures"]))
        families = {row["family"] for row in matrix["fixtures"]}
        for family in ("relay", "dimmer", "key_input", "sensor", "thermostat",
                       "dali_gateway", "wireless_device", "bridge", "pc_interface",
                       "edlt_display", "dlt_display", "programming_method",
                       "usb_bootloader", "power_cycle_rig"):
            with self.subTest(family=family):
                self.assertIn(family, families)
        self.assertEqual(
            {row["bridge_count"] for row in matrix["fixtures"] if row["family"] == "bridge_topology"},
            set(range(1, 7)),
        )

    def test_page_control_remains_the_only_pinned_workflow_receipt(self):
        receipt = load_json(PAGE_CONTROL_RECEIPT)
        self.assertTrue(receipt.get("passed"), "Page Control receipt must stay a passing pin")
        self.assertFalse(receipt.get("physical_device_verified"),
                         "receipt must not claim physical-device acceptance")


if __name__ == "__main__":
    unittest.main()
