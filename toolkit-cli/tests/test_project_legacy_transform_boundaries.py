"""Issue #55 remaining pure-offline boundary: native project repair gaps.

No committed receipt, fixture or documentation describes the native
``TRANSFORM PROJECT`` behavior for a misplaced ``cis`` declaration, Unit
attributes on a firmware rename, a missing ``FirmwareVersion``/``UnitType``,
a non-UTF-8 legacy-transform encoding, or SQLite/Windows repair.
Recovering any of them requires a pinned owned original C-Gate 3.4.0.2001
``TRANSFORM PROJECT`` byte capture plus ``PROJECT LOAD``/``DBGETXML``
readback in ``research/fixtures/project-legacy-transform-*-native-receipt.json``
(or original failure/loadability evidence for SQLite), so the Python model
must not invent these branches. These pins lock the refusal/unmodeled
surface and name the next file to change; they establish no original
GUI, Windows, scanner or hardware acceptance.
"""
from __future__ import annotations

from pathlib import Path
import unittest

from cbus_toolkit.project_legacy_transform import (
    LegacyProjectTransformError,
    NATIVE_TEMPLATE_COVERAGE,
    transform_repaired_legacy_project,
)
from cbus_toolkit.project_repair import ProjectRepairError, repair_project_xml


ROOT = Path(__file__).resolve().parents[1]
HEAD = b'<?xml version="1.0" encoding="utf-8"?><Installation><DBVersion>'
CIS_URI = b"http://www.clipsal.com/cis/schema/2001/cbus.xsd"


def document(version: str, body: bytes) -> bytes:
    return HEAD + version.encode() + b"</DBVersion><Project><Network>" + body + b"</Network></Project></Installation>\n"


def unit(unit_type: str, firmware: str, body: bytes = b"", *, tag: bytes = b"Unit",
         attributes: bytes = b"") -> bytes:
    return (b"<" + tag + attributes + b"><TagName>U</TagName><UnitType>" + unit_type.encode()
            + b"</UnitType><FirmwareVersion>" + firmware.encode() + b"</FirmwareVersion>"
            + b"<CatalogNumber>X</CatalogNumber>" + body + b"</" + tag + b">")


class LegacyRepairBoundaryTests(unittest.TestCase):
    def test_docs_record_branches_as_native_only(self):
        # Next: docs/project-legacy-transform.md must gain a native-backed
        # acceptance paragraph before the Python model implements any of
        # these branches; the doc pins the current unverified surface.
        text = (ROOT / "docs/project-legacy-transform.md").read_text()
        self.assertIn("a\n`cis` declaration elsewhere", text)
        self.assertIn("missing firmware", text)
        self.assertIn("other encodings", text)
        self.assertIn("SQLite repository behavior", text)
        self.assertIn("Windows conversion", text)

    def test_census_keeps_unmodeled_shapes_bounded(self):
        # Next: research/fixtures/project-legacy-transform-template-census.json
        # plus NATIVE_TEMPLATE_COVERAGE must move a bounded entry to full only
        # after a native byte capture; the bounded scopes below are the fence.
        self.assertEqual(
            NATIVE_TEMPLATE_COVERAGE["v2tov21#57-1338c52b"][1],
            "Appends Neo or DLT PP tokens inside cis:Unit; each cis:Unit must carry its own exact cis declaration",
        )
        self.assertIn("attribute-bearing Units rejected",
                      NATIVE_TEMPLATE_COVERAGE["v21tov22#18-8e846bdd"][1])
        self.assertIn("attribute-bearing Units rejected",
                      NATIVE_TEMPLATE_COVERAGE["v21tov22#19-c309fdfb"][1])

    def test_misplaced_cis_declaration_stays_rejected(self):
        # Next: src/cbus_toolkit/project_legacy_transform.py
        # _earlier_unit_migration cis-declaration branch, only after an owned
        # native TRANSFORM PROJECT byte capture for an ancestor-declared
        # cis:Unit plus PROJECT LOAD/DBGETXML readback.
        ancestor = (b"<Network xmlns:cis=\"" + CIS_URI + b"\"><cis:Unit>"
                    b"<TagName>U</TagName><UnitType>KEYB2</UnitType>"
                    b"<FirmwareVersion>1.6</FirmwareVersion><CatalogNumber>X</CatalogNumber>"
                    b"</cis:Unit></Network>")
        source = (HEAD + b"2</DBVersion><Project>" + ancestor
                  + b"</Project></Installation>\n")
        with self.assertRaises(LegacyProjectTransformError) as caught:
            transform_repaired_legacy_project(source)
        self.assertIn("exact cis declaration", str(caught.exception))

    def test_attribute_bearing_firmware_rename_stays_rejected(self):
        # Next: src/cbus_toolkit/project_legacy_transform.py firmware-rename
        # branch, only after an owned native TRANSFORM PROJECT byte capture
        # showing the exact attribute drop and moved FirmwareVersion plus
        # PROJECT LOAD/DBGETXML readback for PC_CTA/PCI-family Units.
        renamed = unit("PC_CTA", "4.00", attributes=b' Extra="1"')
        with self.assertRaises(LegacyProjectTransformError) as caught:
            transform_repaired_legacy_project(document("2.1", renamed))
        self.assertIn("drops Unit attributes", str(caught.exception))
        # The current boundary is narrow: attributes on a non-rename Unit pass
        # through unchanged. A native capture must not be inferred from this.
        passthrough = unit("KEYB2", "1.5", attributes=b' Extra="1"')
        result = transform_repaired_legacy_project(document("2.1", passthrough))
        self.assertIn(b'<Unit Extra="1">', result.transformed_xml)
        self.assertEqual(result.firmware_version_changes, ())

    def test_missing_firmware_or_type_stays_rejected(self):
        # Next: src/cbus_toolkit/project_legacy_transform.py Unit-profile
        # branch, only after an owned native TRANSFORM PROJECT capture for a
        # Unit without FirmwareVersion/UnitType plus load/readback.
        bodies = (
            b"<Unit><TagName>U</TagName><UnitType>KEYB2</UnitType>"
            b"<CatalogNumber>X</CatalogNumber></Unit>",
            b"<Unit><TagName>U</TagName><FirmwareVersion>1.5</FirmwareVersion>"
            b"<CatalogNumber>X</CatalogNumber></Unit>",
            b"<Unit><TagName>U</TagName><UnitType>KEYB2</UnitType>"
            b"<FirmwareVersion></FirmwareVersion><CatalogNumber>X</CatalogNumber></Unit>",
        )
        for body in bodies:
            with self.subTest(body=body):
                with self.assertRaises(LegacyProjectTransformError) as caught:
                    transform_repaired_legacy_project(document("2.1", body))
                self.assertTrue(
                    "one UnitType and FirmwareVersion" in str(caught.exception)
                    or "noncanonical empty elements" in str(caught.exception),
                    str(caught.exception),
                )

    def test_non_utf8_legacy_encodings_stay_rejected(self):
        # Next: src/cbus_toolkit/project_legacy_transform.py envelope branch,
        # only after an owned native TRANSFORM PROJECT byte diff for a
        # non-UTF-8 repaired encoding plus PROJECT LOAD/DBGETXML readback.
        for encoding in ("ISO-8859-1", "windows-1252", "US-ASCII"):
            with self.subTest(encoding=encoding):
                source = (f'<?xml version="1.0" encoding="{encoding}"?><Installation>'
                          "<DBVersion>2.2</DBVersion><Project/></Installation>\n").encode()
                with self.assertRaises(LegacyProjectTransformError) as caught:
                    transform_repaired_legacy_project(source)
                self.assertIn("UTF-8 Python-repaired", str(caught.exception))

    def test_sqlite_bytes_stay_refused(self):
        # Next: src/cbus_toolkit/project_repair.py SQLite/Windows repair
        # branch (no such branch exists yet; repair only handles XML bytes).
        # Implementing it needs original failure/loadability evidence with
        # input backups and a recoverable-vs-unsupported distinction.
        data = b"SQLite format 3\x00" + b"\x00" * 64
        with self.assertRaises(ProjectRepairError):
            repair_project_xml(data)
        with self.assertRaises(LegacyProjectTransformError):
            transform_repaired_legacy_project(data)

    def test_no_sqlite_repair_surface_in_legacy_modules(self):
        # Next: project_repair.py / project_legacy_transform.py SQLite repair
        # routines, only after original evidence exists; an unbuilt boundary
        # must not imply a surface.
        import cbus_toolkit.project_legacy_transform as legacy
        import cbus_toolkit.project_repair as repair

        for module in (legacy, repair):
            with self.subTest(module=module.__name__):
                leaked = [name for name in dir(module) if "sqlite" in name.lower()]
                self.assertEqual(leaked, [])


if __name__ == "__main__":
    unittest.main()
