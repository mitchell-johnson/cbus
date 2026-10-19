"""P8.02 wave-25 narrow offline pin for #56 (report enumeration guards).

Pins pure-offline enumeration guards in
``cbus_toolkit.project_documentation`` only: the heading-only unit-type
set, the unassigned/trigger addresses with standard application titles,
the progress/date literals, and the Application PP number guard consumed
by the base documentor. No server, hardware, GUI, vendor EXE, eDLT,
wireless, firmware, Rust, or parity-register claim; #56 stays OPEN.

Each pinned constant/guard below had zero prior refs in ``tests/``:
``doc.HEADING_ONLY_TYPES`` (including the never-exercised ``XC305B``
member), ``doc.UNASSIGNED`` / ``doc.TRIGGER_APPLICATION`` /
``doc.STANDARD_APPLICATION_TITLES`` as ``doc.<name>`` references,
``doc.PROGRESS_TEXT`` / ``doc.PROGRESS_TITLE`` /
``doc.DATE_FORMAT_DELPHI``, and ``doc._application_numbers``.
"""

from __future__ import annotations

import unittest
from datetime import datetime

from cbus_toolkit import project_documentation as doc


def _bare_network():
    return doc.Network(254, "Local", "", "", [], [])


def _unit(unit_type="BURDEN", address=1, params=None):
    return doc.Unit(address, f"U{address}", unit_type, "", "", "", "",
                    dict(params or {}), {})


class HeadingOnlyEnumerationWave25Tests(unittest.TestCase):
    def test_heading_only_set_exact_and_case_sensitive(self):
        # Next: native heading-only set / PCI parity stays open.
        self.assertEqual(doc.HEADING_ONLY_TYPES, ("BURDEN", "XC100B", "XC305B"))
        for unit_type in doc.HEADING_ONLY_TYPES:
            net = _bare_network()
            model = doc.ProjectModel("T", [net])
            out = doc._Writer()
            record = doc.document_unit(out, net, _unit(unit_type), model)
            self.assertEqual(record["status"], "heading_only")
            self.assertIsNone(record["documentor"])
            self.assertEqual(out.lines, [
                f'<h3><a name="254_unit_1">U1 - {unit_type}</a>'
                ' [ <a href="#contents">top</a> ]</h3>'])
        # Lowercase is NOT heading-only: InsertHTMLUnit compares verbatim,
        # so "burden" falls through to the base documentor.
        net = _bare_network()
        model = doc.ProjectModel("T", [net])
        out = doc._Writer()
        record = doc.document_unit(out, net, _unit("burden"), model)
        self.assertEqual(record["status"], "recovered")
        self.assertEqual(record["documentor"], "TUnitTypeDocumentor")
        self.assertIn("Unit Address: 1<br />", out.lines)


class UnassignedTriggerTitlesWave25Tests(unittest.TestCase):
    def test_unassigned_trigger_and_standard_titles(self):
        # Next: native application-registry title selection stays open.
        self.assertEqual(doc.UNASSIGNED, 255)
        self.assertEqual(doc.TRIGGER_APPLICATION, 202)
        self.assertEqual(doc.STANDARD_APPLICATION_TITLES[0x38], "Lighting")
        self.assertEqual(doc.STANDARD_APPLICATION_TITLES[0xCA], "Trigger Control")
        self.assertEqual(doc.STANDARD_APPLICATION_TITLES[0xFF], "<Unused>")
        bare = _bare_network()
        self.assertEqual(doc.html_application(bare, 0xCA),
                         '<a href="#254_202">Trigger Control</a>')
        self.assertEqual(doc.html_application(bare, 99), '<a href="#254_99">99</a>')
        self.assertEqual(doc.html_application(bare, doc.UNASSIGNED), "<Unused>")
        self.assertNotIn("href", doc.html_application(bare, doc.UNASSIGNED))
        self.assertEqual(
            doc.html_group(bare, 56, doc.Group(doc.UNASSIGNED, "A<B>", "", [])),
            "A&#60;B&#62;")


class ProgressDateLiteralsWave25Tests(unittest.TestCase):
    def test_progress_and_delphi_date_literals(self):
        # Next: progress dialog / printing parity stays unassessed.
        self.assertEqual(doc.PROGRESS_TEXT, "Network %d of %d")
        self.assertEqual(doc.PROGRESS_TITLE, "Generating Documentation")
        self.assertEqual(doc.DATE_FORMAT_DELPHI, "dd mmm yyyy hh:mm")
        self.assertEqual(doc.PROGRESS_TEXT % (1, 2), "Network 1 of 2")
        self.assertEqual(doc.delphi_date(datetime(2026, 12, 3, 7, 5)),
                         "03 Dec 2026 07:05")


class ApplicationPpGuardWave25Tests(unittest.TestCase):
    def test_application_pp_enumeration_guard(self):
        # Next: stored Application PP shape beyond the first pair stays open.
        def numbers(value):
            params = {} if value is None else {"Application": value}
            return doc._application_numbers(_unit("PC_GIM", 12, params))

        self.assertEqual(numbers(None), (None, None))
        self.assertEqual(numbers(""), (None, None))
        self.assertEqual(numbers("56"), (56, None))
        self.assertEqual(numbers("56 255"), (56, 255))
        self.assertEqual(numbers("$38 255"), (56, 255))
        self.assertEqual(numbers("56 255 1"), (56, 255))
        net = _bare_network()
        out = doc._Writer()
        doc.document_base(out, net, _unit("PC_GIM", 12))
        self.assertFalse([line for line in out.lines
                          if line.startswith("Application:")
                          or line.startswith("Secondary Application:")])
        out = doc._Writer()
        doc.document_base(out, net, _unit("PC_GIM", 12, {"Application": "56 255"}))
        self.assertIn('Application: <a href="#254_56">Lighting</a><br />', out.lines)
        self.assertIn("Secondary Application: <Unused><br />", out.lines)


if __name__ == "__main__":
    unittest.main()
