import tempfile
import unittest
from pathlib import Path

from cbus_toolkit.inventory import InventoryError, read_commands, read_help_contents, read_unit_catalog


class InventoryTests(unittest.TestCase):
    def test_hhc_entities_and_nested_depth(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "help.hhc"
            p.write_text('<UL><LI><OBJECT type="text/sitemap"><param name="Name" value="Networks &amp; Units">'
                         '<param name="Local" value="7.htm"></OBJECT><UL><LI><OBJECT type="text/sitemap">'
                         '<param name="Name" value="Scan"></OBJECT></UL></UL>')
            self.assertEqual(read_help_contents(p), [
                {"depth": 1, "title": "Networks & Units", "file": "7.htm"},
                {"depth": 2, "title": "Scan"}])

    def test_command_blocks_preserve_syntax(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cmds.txt"
            p.write_text('ON\nSyntax:\nON group\ngroup = address\nDescription:\nSwitch on.\n~#~\n')
            self.assertEqual(read_commands(p), [{"command": "ON", "syntax": "ON group\ngroup = address",
                                                 "description": "Switch on."}])
            p.write_text(p.read_text() * 2)
            with self.assertRaises(InventoryError):
                read_commands(p)

    def test_catalog_retains_unknown_fields_and_firmware_ranges(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cbusunits.xml"
            p.write_text('<CBusUnits><Units><Unit><CatalogNumber>TEST</CatalogNumber><NewField>yes</NewField>'
                         '<FirmwareRevisions><Revision><UnitType>KEY1</UnitType><MinVersion>1.2.3</MinVersion>'
                         '</Revision></FirmwareRevisions></Unit></Units></CBusUnits>')
            result = read_unit_catalog(p)
            self.assertEqual(result[0]["NewField"], "yes")
            self.assertEqual(result[0]["FirmwareRevisions"][0]["MinVersion"], "1.2.3")
            p.write_text('<!DOCTYPE a [<!ENTITY x "x">]><CBusUnits/>')
            with self.assertRaises(InventoryError):
                read_unit_catalog(p)


if __name__ == "__main__":
    unittest.main()
