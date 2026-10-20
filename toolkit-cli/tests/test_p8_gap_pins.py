"""P8 gap pins (#55-#59): lock current refusal/unknown boundaries, name next file.

Each test pins one explicit small slice at the current head and documents the
remaining gap plus the next file to change. None of these establish original
Windows/GUI/hardware acceptance.
"""
import unittest

from cbus_toolkit.cgate import CGateError, CGateResponse
from cbus_toolkit.networks import direct_network_path
from cbus_toolkit.project_documentation import resolve_report_network_selector
from cbus_toolkit.project_repair import ProjectRepairError, repair_project_xml
from cbus_toolkit.project_topology import ORPHAN_TEXT, PARITY, UNASSESSED
from cbus_toolkit.unit_diagnostics import NetworkDiagnostics


def _response(lines, code=None):
    code = int(lines[-1][:3]) if code is None else code
    return CGateResponse(tuple(lines), lines[-1], code)


class P8GapPinTests(unittest.TestCase):
    def test_p55_sqlite_bytes_stay_refused(self):
        # Next: project_repair.py SQLite/Windows repair branch (no such
        # branch exists yet; repair only handles XML bytes).
        data = b"SQLite format 3\x00" + b"\x00" * 64
        with self.assertRaises(ProjectRepairError) as caught:
            repair_project_xml(data)
        self.assertIn(caught.exception.stage, ("bounds", "manual", "repair", "tidy", "verify"))

    def test_p56_report_selector_validation_precedes_manager_order(self):
        # Next: project_documentation.py report-manager enumeration order;
        # native manager order remains unestablished.
        with self.assertRaises(Exception):
            resolve_report_network_selector(None, 1.5)
        with self.assertRaises(Exception):
            resolve_report_network_selector(None, 256)

    def test_p57_topology_print_and_clipboard_parity_stay_open(self):
        # Next: project_topology.py print/image export and clipboard copy.
        self.assertEqual(PARITY["print_parity"], UNASSESSED)
        self.assertEqual(PARITY["clipboard_copy"], "not_implemented")
        self.assertIn("is not accessible", ORPHAN_TEXT)

    def test_p58_no_piced_launcher_surface_in_barcode_modules(self):
        # Next: barcode_database.py Toolkit-owned PICED/controller handoff
        # boundary; KEYGL5/Hydra scanner routines also remain open.
        import cbus_toolkit.barcode_database as database
        import cbus_toolkit.barcode_scanner as scanner
        for module in (database, scanner):
            leaked = [name for name in dir(module) if "piced" in name.lower()]
            self.assertEqual(leaked, [])

    def test_p59_routed_and_local_pci_shapes_stay_refused(self):
        # Next: unit_diagnostics.py routed requests and local-PCI Psync.
        for bad in ("//PROJ/1/2", "//PROJ/abc", "PROJ/254", ""):
            with self.assertRaises(ValueError):
                direct_network_path(bad)

    def test_p59_per_unit_failure_is_unknown_never_zero(self):
        # Next: unit_diagnostics.py electrical/clock/burden measurement
        # validation against physical fixtures.
        network = "//DIAG/7"

        class Stub:
            def command(self, text):
                if text == "DBGETXML " + network:
                    return _response(["347-<Network><Address>7</Address>"
                                      "<Unit><Address>5</Address><UnitType>DIMDN4</UnitType></Unit>"
                                      "</Network>", "344 End XML snippet"])
                if text == "NET PINGU " + network:
                    return _response(["302-Units=5", "200 OK."])
                if text.endswith(" NetVoltage"):
                    raise CGateError(_response(["404 Not found"], code=404))
                raise AssertionError("unexpected command: " + text)

        report = NetworkDiagnostics(Stub()).diagnose(network, burden=False, clock=False)
        (row,) = report.units
        self.assertEqual(row.voltage, "unknown")
        self.assertNotEqual(row.voltage, 0)


if __name__ == "__main__":
    unittest.main()
