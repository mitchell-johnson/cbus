"""P8 wave-10 narrow offline pin for #58 (barcode scanner).

One narrow slice: AddUnitByCatalogCode offline branch order
(catalog_add_outcome) plus the software-config field split it consumes.
Pure-offline only: no server, GUI, hardware, PP, or original execution.
#58 stays OPEN; Toolkit-owned PICED/controller handoff boundary in
barcode_database.py and KEYGL5/Hydra routines remain untouched.
"""
from __future__ import annotations

import unittest

from cbus_toolkit import barcode_scanner as scanner


class P58CatalogOutcomePrecedenceWave10Tests(unittest.TestCase):
    """Site-open/serial-found precede type lookup; unknown type precedes node."""

    def test_site_closed_and_serial_found_precede_type_check(self):
        # Next: barcode_database.py PICED/controller handoff; no PP/save here.
        self.assertEqual(
            scanner.catalog_add_outcome(site_open=False, serial_found=True,
                                        type_known=False)["outcome"], "ignored")
        self.assertEqual(
            scanner.catalog_add_outcome(serial_found=True,
                                        type_known=False)["outcome"],
            "selected_existing")
        self.assertEqual(
            scanner.catalog_add_outcome(type_known=False)["message_id"], 2099)

    def test_unknown_type_units_node_and_database_full_order(self):
        # Next: same handoff boundary; physical scanner/GUI timing stays open.
        self.assertEqual(
            scanner.catalog_add_outcome(type_known=False,
                                        units_node=False)["message_id"], 2099)
        self.assertEqual(
            scanner.catalog_add_outcome(units_node=False)["outcome"], "ignored")
        self.assertEqual(
            scanner.catalog_add_outcome(unit_count=255)["message_id"], 2066)
        self.assertEqual(
            scanner.catalog_add_outcome(unit_count=254)["outcome"], "add")


class P58WirelessMismatchWave10Tests(unittest.TestCase):
    """Wired/wireless family mismatch errors; matching families add."""

    def test_wired_wireless_mismatch_order(self):
        # Next: barcode_database.py handoff; KEYGL5/Hydra routines stay open.
        self.assertEqual(
            scanner.catalog_add_outcome(network_wireless=True,
                                        family="Wired Relay")["message_id"],
            45151)
        self.assertEqual(
            scanner.catalog_add_outcome(network_wired=True,
                                        family="Wireless Switch")["message_id"],
            45152)
        self.assertEqual(
            scanner.catalog_add_outcome(network_wired=True,
                                        family="Wired Relay")["outcome"], "add")
        self.assertEqual(
            scanner.catalog_add_outcome(network_wireless=True,
                                        family="Wireless Switch")["outcome"],
            "add")


class P58SoftwareConfigSplitWave10Tests(unittest.TestCase):
    """Field split: truncators, comma-substitute rewrite, serial trim."""

    def test_truncators_comma_substitute_and_serial_trim(self):
        # Next: same handoff boundary; no catalogue lookup or project save.
        dash = scanner.split_software_config("5100AUX-123456  " + "000123456789")
        self.assertEqual(dash.catalog_field, "5100AUX-123456")
        self.assertEqual(dash.catalog_lookup, "5100AUX")
        self.assertEqual(dash.serial, "000123456789")
        comma = scanner.split_software_config("5100AUX,123456  " + "000123456789")
        self.assertEqual(comma.catalog_lookup, "5100AUX")
        rewritten = scanner.split_software_config("AB¼CD1234567890 " + "000123456789")
        self.assertEqual(rewritten.catalog_field, "AB,CD1234567890")
        self.assertEqual(rewritten.catalog_lookup, "AB")
        padded = scanner.split_software_config("  5100AUX 12345 " + "  000123456789  ")
        self.assertEqual(padded.catalog_field, "5100AUX 12345")
        self.assertEqual(padded.catalog_lookup, "5100AUX")
        self.assertEqual(padded.serial, "000123456789")
        with self.assertRaises(scanner.BarcodeError) as caught:
            scanner.split_software_config("short")
        self.assertEqual(caught.exception.details.get("code"), "wrong_barcode")

    def test_unidentified_serials_never_match(self):
        # Next: same handoff boundary; UnitBySerialNumber equality only.
        self.assertEqual(scanner.displayable_serial("000000000000"), "No serial #")
        self.assertEqual(scanner.displayable_serial("010485754095"), "No serial #")
        self.assertFalse(scanner.serials_match("000000000000", "000000000000"))
        self.assertFalse(scanner.serials_match("010485754095", "010485754095"))
        self.assertTrue(scanner.serials_match("  000123456789  ", "000123456789"))


if __name__ == "__main__":
    unittest.main()
