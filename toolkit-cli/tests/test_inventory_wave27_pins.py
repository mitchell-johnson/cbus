"""Wave-27 narrow offline pin for inventory guards.

Pins pure-offline guards in ``cbus_toolkit.inventory`` only: the
command-name allowlist, the Syntax-less block skip, the catalog root-tag
guard, and the VendorInventory jar/help-contents guards. No server,
hardware, GUI, vendor distribution, Rust, eDLT HVAC, thermostat
scheduling, or parity-register claim; P-series issues stay OPEN.

Each pinned guard below had zero prior refs in ``tests/``:
``inventory.VendorInventory`` as an attribute reference, the
``Unrecognized command name`` guard, blocks without a ``Syntax:`` marker
being skipped, the ``Expected a CBusUnits catalog`` guard (American
spelling; unrelated ``catalogue`` strings live in other modules), the
``C-Gate directory must contain cgate.jar`` guard, the ``Specify the
extracted Toolkit help directory`` guard, and the ``Expected exactly one
.hhc contents file`` guard.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cbus_toolkit import inventory
from cbus_toolkit.inventory import InventoryError, read_commands, read_unit_catalog


class CommandNameAllowlistWave27Tests(unittest.TestCase):
    def test_lowercase_command_name_rejected(self):
        # Next: C-Gate command admission beyond the name gate stays open.
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cmds.txt"
            p.write_text("on\nSyntax:\non group\nDescription:\nSwitch on.\n~#~\n")
            with self.assertRaisesRegex(InventoryError, "Unrecognized command name"):
                read_commands(p)


class SyntaxLessBlocksWave27Tests(unittest.TestCase):
    def test_blocks_without_syntax_marker_are_skipped(self):
        # Next: command-block recovery beyond the Syntax gate stays open.
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cmds.txt"
            p.write_text("NOT A COMMAND BLOCK\njust prose\n~#~\n"
                         "ON\nSyntax:\nON group\nDescription:\nSwitch on.\n~#~\n")
            self.assertEqual(read_commands(p), [
                {"command": "ON", "syntax": "ON group", "description": "Switch on."}])


class CatalogRootTagWave27Tests(unittest.TestCase):
    def test_wrong_root_tag_rejected(self):
        # Next: unit-spec admission beyond the root gate stays open.
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cbusunits.xml"
            p.write_text("<Units></Units>")
            with self.assertRaisesRegex(InventoryError, "Expected a CBusUnits catalog"):
                read_unit_catalog(p)


class VendorInventoryGuardsWave27Tests(unittest.TestCase):
    def test_missing_jar_and_help_contents_rejected(self):
        # Next: vendor-distribution inventory beyond these gates stays open.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with self.assertRaisesRegex(InventoryError, "must contain cgate.jar"):
                inventory.VendorInventory(root)
            root.joinpath("cgate.jar").write_bytes(b"fake")
            with self.assertRaisesRegex(InventoryError, "extracted Toolkit help directory"):
                inventory.VendorInventory(root).help_topics()
            help_dir = root / "help"
            help_dir.mkdir()
            with self.assertRaisesRegex(InventoryError, "exactly one .hhc"):
                inventory.VendorInventory(root, help_dir=help_dir).help_topics()
            help_dir.joinpath("a.hhc").write_text("<html></html>")
            help_dir.joinpath("b.hhc").write_text("<html></html>")
            with self.assertRaisesRegex(InventoryError, "exactly one .hhc"):
                inventory.VendorInventory(root, help_dir=help_dir).help_topics()


if __name__ == "__main__":
    unittest.main()
