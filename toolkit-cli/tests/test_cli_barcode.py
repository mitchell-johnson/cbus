"""CLI coverage for barcode parse and offline project add-unit."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

from test_barcode_scanner import CATALOG_XML, PROJECT_XML

ROOT = Path(__file__).resolve().parents[1]


class BarcodeCLITests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        self.catalog = self.dir / "cbusunits.xml"
        self.catalog.write_text(CATALOG_XML)
        self.project = self.dir / "p.xml"
        self.project.write_text(PROJECT_XML)

    def cli(self, *args, status=0, stdin=None):
        env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), os.environ.get("PYTHONPATH", "")])}
        env.pop("CBUS_UNIT_CATALOG", None)
        process = subprocess.run([sys.executable, "-m", "cbus_toolkit", *map(str, args)], input=stdin,
                                 text=True, capture_output=True, env=env)
        self.assertEqual(process.returncode, status, process.stderr + process.stdout)
        return json.loads(process.stdout if process.stdout else process.stderr)

    def test_parse_argument_and_wedge_stdin(self):
        one = self.cli("barcode", "parse", "5031NL          123456789012")
        self.assertEqual(one["count"], 1)
        self.assertEqual(one["scans"][0]["units_view"]["actions"][0]["catalog_lookup"], "5031NL")
        many = self.cli("barcode", "parse", stdin="123456789012\r\n\r\n9312345678901\r\n")
        self.assertEqual([scan["unit_dialog"]["accepted"] for scan in many["scans"]], [True, False])
        self.assertEqual(self.cli("barcode", "parse", stdin="\r\n", status=1)["code"], "empty_input")

    def test_add_unit_xml_and_selection(self):
        added = self.cli("project", "add-unit", self.project, "--network", "254", "--catalog", self.catalog,
                         "--barcode", "5031NL          123456789012", "--tag-name", "Kitchen")
        self.assertEqual((added["result"]["unit"], added["result"]["tag_name"]), ("/network/254/unit/2", "Kitchen"))
        shown = self.cli("project", "get", self.project, "/network/254/unit/2")
        self.assertEqual(shown["fields"]["SerialNumber"], "12345678.9012")
        again = self.cli("project", "add-unit", self.project, "--network", "254", "--catalog", self.catalog,
                         "--barcode", "-", stdin="5031NL          123456789012\r\n")
        self.assertEqual((again["file"], again["result"]["action"]), (None, "selected_existing"))

    def test_add_unit_cbz_output_copy(self):
        archive = self.dir / "p.cbz"
        self.cli("project", "export", self.project, archive, "--format", "cbz")
        copy = self.dir / "copy.cbz"
        self.cli("project", "add-unit", archive, "--network", "254", "--catalog", self.catalog,
                 "--barcode", "E3031D          000000000501", "--address", "200", "--output", copy)
        with ZipFile(copy) as bundle:
            self.assertIn(b"<Address>200</Address>", b"".join(bundle.read(name) for name in bundle.namelist()))
        self.assertEqual(self.cli("project", "list", archive, "/network/254", "--kind", "unit").__len__(), 2)

    def test_add_unit_errors_leave_file_unchanged(self):
        before = self.project.read_bytes()
        for barcode, code in (("ZZZ             123456789012", "unknown_unit_type"), ("12345", "wrong_barcode"),
                              ("A\nB", "invalid_input")):
            error = self.cli("project", "add-unit", self.project, "--network", "254", "--catalog", self.catalog,
                             "--barcode", barcode, status=1)
            self.assertEqual(error["code"], code)
        self.assertEqual(self.project.read_bytes(), before)
        error = self.cli("project", "add-unit", self.project, "--network", "254", "--barcode", "x" * 28, status=1)
        self.assertIn("CBUS_UNIT_CATALOG", error["error"])


if __name__ == "__main__":
    unittest.main()
