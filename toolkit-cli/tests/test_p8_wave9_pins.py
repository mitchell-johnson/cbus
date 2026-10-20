"""P8 wave-9 narrow offline pin for issues 55-59.

One narrow slice: offline refusal/unknown boundaries stay explicit and make
no native/vendor claim. Pure-offline only: no server, GUI, hardware, or
original execution. Issues 55-59 stay OPEN; issue 59 (diagnostics/electrical)
is untouched here -- next file `src/cbus_toolkit/unit_diagnostics.py`.
"""
from __future__ import annotations

import unittest
from datetime import datetime

from cbus_toolkit import barcode_scanner as scanner
from cbus_toolkit import project_documentation as doc
from cbus_toolkit import project_repair as repair


class P55RepairRefusalWave9Tests(unittest.TestCase):
    """project_repair.py (#55): NUL/size/stage refused; no native load claimed."""

    def test_nul_size_and_stage_stay_refused_without_native_claim(self):
        # Next: project_repair.py SQLite/Windows branch + native LOAD of new
        # outputs (repair only handles XML bytes; native_load_verified False).
        with self.assertRaises(repair.ProjectRepairError) as caught:
            repair.transform_project_repair_xml(b"<a>\x00</a>", stage="repair")
        self.assertEqual(caught.exception.stage, "repair")
        with self.assertRaises(repair.ProjectRepairError) as caught:
            repair.preprocess_project_xml(b"a" * 10, max_bytes=5)
        self.assertEqual(caught.exception.stage, "bounds")
        with self.assertRaises(ValueError):
            repair.transform_project_repair_xml(b"<a/>", stage="bogus")
        result = repair.repair_project_xml(
            b'<?xml version="1.0" encoding="utf-8"?>'
            b"<Installation><Project><TagName>P</TagName></Project></Installation>"
        )
        self.assertFalse(result.as_dict()["native_load_verified"])
        self.assertFalse(result.as_dict()["file_modified"])


class P5657DocumentationHelpersWave9Tests(unittest.TestCase):
    """project_documentation.py (#56/#57): pure helper determinism, no GUI order."""

    def test_version_select_format_and_fallback_stay_deterministic(self):
        # Next: project_documentation.py report-manager order + whole-page
        # byte/visual parity (explicit address order only here).
        self.assertEqual(doc.version_compare("1.5.03", "1.5.3"), 0)
        self.assertEqual(doc.version_compare("1.5.03", "1.5.02"), 1)
        self.assertEqual(doc.select_documentor("NOPE_XYZ", "1.00"), "UnitType")
        self.assertEqual(doc.select_documentor("keya1", "1.4.00"), "NeoInput")
        self.assertEqual(doc.format_html_string("a<b>"), "a&#60;b&#62;")
        self.assertEqual(doc.delphi_date(datetime(2026, 1, 5, 9, 7)), "05 Jan 2026 09:07")
        network = doc.Network(254, "Net", "PCI", "COM1", [], [])
        self.assertEqual(doc.html_application(network, 255), "<Unused>")
        self.assertIn("Lighting", doc.html_application(network, 0x38))


class P58WedgeUnitsViewWave9Tests(unittest.TestCase):
    """barcode_scanner.py (#58): wedge split + Units-view ignored boundary."""

    def test_wedge_drops_cr_and_short_nonzero_scans_stay_ignored(self):
        # Next: barcode_database.py PICED/controller handoff + KEYGL5/Hydra
        # routines; physical scanner/GUI timing stays open.
        self.assertEqual(scanner.wedge_lines("abc\r\n\r\ndef\rghi"), ["abc", "defghi"])
        self.assertEqual(scanner.wedge_lines(""), [])
        parsed = scanner.parse("short")
        self.assertTrue(parsed["units_view"]["ignored"])
        self.assertEqual(parsed["units_view"]["actions"], [])
        self.assertFalse(parsed["unit_dialog"]["accepted"])
        found = scanner.parse("011111")
        self.assertFalse(found["units_view"]["ignored"])
        self.assertEqual(found["units_view"]["actions"][0]["action"], "find_by_serial")
        with self.assertRaises(scanner.BarcodeError) as caught:
            scanner.split_software_config("short")
        self.assertEqual(caught.exception.details.get("code"), "wrong_barcode")


class P58DialogAcquireWave9Tests(unittest.TestCase):
    """barcode_scanner.py (#58): dialog accept/reject + 75 ms idle edge."""

    def test_dialog_retail_rejected_serial_accepted_idle_edge_exact(self):
        # Next: same as above; no PP defaults or project save implied here.
        self.assertFalse(scanner.unit_dialog_serial("93" + "x" * 11)["accepted"])
        accepted = scanner.unit_dialog_serial("123456789012")
        self.assertTrue(accepted["accepted"])
        self.assertEqual(accepted["stored_serial"], "12345678.9012")
        self.assertEqual(accepted["message_id"], 2150)
        self.assertEqual(
            scanner.acquire([("key", "A", 0), ("timer", None, 75)])["completed"], False
        )
        self.assertEqual(
            scanner.acquire([("key", "A", 0), ("timer", None, 76)])["completed"], True
        )


if __name__ == "__main__":
    unittest.main()
