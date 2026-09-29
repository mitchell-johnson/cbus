"""Keep the migration-template census, portable mapping and constants in step."""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import unittest
from xml.etree import ElementTree as ET

from cbus_toolkit import project_legacy_transform as portable


ROOT = Path(__file__).resolve().parents[1]
CENSUS = ROOT / "research/fixtures/project-legacy-transform-template-census.json"
STYLESHEETS = {
    "projectversions.xml": "f9b2e0a83753321e311dee1ac7e1817b28dd984a792a2fd2923efa1cac85aaf8",
    "v2tov21.xslt": "8346eab4259b957d53fc2b5c14ee1e058196124eabe4a7e3fb45b145f74735a8",
    "v21tov22.xslt": "e2090621171b5febf4903eaa964dd7a855b3d3cea827678da3758376dceab875",
    "v22tov23.xslt": "5674534824826a2db5e3b762c207ce0e566298e54703f628d16f9b3d2d47dab2",
}
COUNTS = {"v2tov21.xslt": (57, 57), "v21tov22.xslt": (19, 19), "v22tov23.xslt": (2, 2)}
XSL = "{http://www.w3.org/1999/XSL/Transform}"


def census() -> dict:
    return json.loads(CENSUS.read_bytes())


def rows(**where) -> list[dict]:
    return [row for row in census()["templates"]
            if all(row[key] == value for key, value in where.items())]


def one(**where) -> dict:
    found = rows(**where)
    assert len(found) == 1, where
    return found[0]


class TemplateCensusTests(unittest.TestCase):
    def test_census_is_canonical_pinned_and_sanitized(self):
        raw = CENSUS.read_bytes()
        data = json.loads(raw)
        self.assertEqual(raw.decode(), json.dumps(data, indent=2) + "\n")
        self.assertEqual(data["format"], "cbus-project-legacy-transform-template-census-v1")
        self.assertEqual(data["sources"], STYLESHEETS)
        self.assertEqual(data["chain"], [["2", "2.1", "v2tov21.xslt"], ["2.1", "2.2", "v21tov22.xslt"],
                                         ["2.2", "2.3", "v22tov23.xslt"]])
        # No stylesheet body text: only IDs, hashes, short matches and identifiers.
        self.assertNotIn(b"xsl:", raw)
        self.assertNotIn(b"0xff", raw)
        for row in data["templates"]:
            self.assertLessEqual(len(row.get("match", "")), 64)
            self.assertEqual(row["match_sha256"], sha256(row["match"].encode()).hexdigest()
                             if "match" in row else row["match_sha256"])

    def test_ids_are_unique_ordered_and_counted(self):
        data = census()
        ids = [row["id"] for row in data["templates"]]
        self.assertEqual(len(ids), len(set(ids)))
        for stylesheet, (total, covered) in COUNTS.items():
            own = [row for row in data["templates"] if row["stylesheet"] == stylesheet]
            self.assertEqual([row["ordinal"] for row in own], list(range(1, total + 1)))
            self.assertTrue(all(row["id"].startswith(stylesheet.removesuffix(".xslt") + "#")
                                for row in own))
            summary = data["summary"][stylesheet]
            self.assertEqual((summary["templates"], summary["covered"]), (total, covered))
            self.assertEqual(summary["full"] + summary["bounded"], summary["covered"])
            self.assertEqual(summary["full"], sum(row["portable_extent"] == "full" for row in own))
        self.assertEqual(data["summary"]["total"]["templates"], 78)

    def test_portable_flags_are_derived_from_the_module_mapping(self):
        mapping = portable.NATIVE_TEMPLATE_COVERAGE
        data = census()
        self.assertEqual(set(mapping) - {row["id"] for row in data["templates"]}, set())
        for row in data["templates"]:
            with self.subTest(template=row["id"]):
                coverage = mapping.get(row["id"])
                self.assertEqual(row["portable_coverage"], coverage is not None)
                self.assertEqual((row["portable_extent"], row["portable_scope"]),
                                 coverage if coverage else (None, None))
                if coverage:
                    self.assertIn(coverage[0], ("full", "bounded"))

    def test_module_constants_match_census_identifiers(self):
        def removals(stylesheet):
            return {name for row in rows(stylesheet=stylesheet, classification="parameter-removal")
                    for name in row["selected_pp"]}

        self.assertEqual(removals("v2tov21.xslt"), portable._V2_PP_REMOVED)
        self.assertEqual(removals("v21tov22.xslt"), portable._V21_PP_REMOVED)
        expansion = one(stylesheet="v2tov21.xslt", classification="parameter-expansion")
        self.assertEqual(expansion["selected_pp"], [portable._V2_EXPANDED])
        self.assertEqual(expansion["created"],
                         ["PP:" + portable._V2_EXPANDED] +
                         ["PP:" + name for name, _ in portable._V2_EXPANSION])
        rename = one(classification="parameter-rename")
        self.assertEqual({rename["selected_pp"][0]: rename["created"][0][3:]}, portable._V2_RENAMED)
        added = one(classification="namespace-parameter-addition")
        self.assertEqual(set(added["unit_types"]), portable._NEO_TYPES | portable._DLT_TYPES)
        self.assertEqual(set(added["firmware_prefixes"]), set(portable._NEO_ADDED_PREFIXES))
        self.assertEqual(added["created"], ["PP:" + name for name, _ in
                                            (*portable._NEO_ADDED, *portable._DLT_ADDED)])
        dlt, neo = rows(classification="conditional-parameter-removal")
        self.assertEqual((set(dlt["unit_types"]), set(dlt["selected_pp"]), dlt["condition_pp"]),
                         (portable._DLT_TYPES, portable._DLT_WITHOUT_APPLICATION_REMOVED,
                          ["Application"]))
        self.assertEqual((set(neo["unit_types"]), neo["firmware_prefixes"], set(neo["selected_pp"])),
                         (portable._NEO_TYPES, [portable._NEO_WITHOUT_APPLICATION_PREFIX],
                          portable._NEO_WITHOUT_APPLICATION_REMOVED))
        wireless = one(classification="parameter-addition")
        self.assertEqual((set(wireless["unit_types"]), wireless["firmware_prefixes"],
                          wireless["condition_pp"]),
                         (portable._WIRELESS_TYPES, [portable._WIRELESS_PREFIX], ["Application"]))
        self.assertEqual(wireless["created"], ["PP:" + name for name, _ in portable._WIRELESS_ADDED])
        renames = rows(classification="firmware-rename")
        self.assertEqual([(set(row["unit_types"]), row["firmware_prefixes"][0]) for row in renames],
                         [(set(types), prefix) for types, prefix, _ in portable._FIRMWARE_RENAMES])


@unittest.skipUnless(os.environ.get("CBUS_LOCAL_CGATE_VENDOR"),
                     "Select the pinned vendor C-Gate app directory to regenerate the census")
class VendorTemplateCensusTests(unittest.TestCase):
    def test_regenerated_census_is_deterministic_and_committed(self):
        from research.legacy_transform_template_census import render

        vendor = Path(os.environ["CBUS_LOCAL_CGATE_VENDOR"])
        first = render(vendor)
        self.assertEqual(first, render(vendor))
        self.assertEqual(first, CENSUS.read_text())

    def test_created_values_match_the_vendor_stylesheets(self):
        transform = Path(os.environ["CBUS_LOCAL_CGATE_VENDOR"]) / "transform"

        def created(stylesheet, ordinal):
            template = ET.parse(transform / stylesheet).getroot().findall(XSL + "template")[ordinal - 1]
            pairs = []
            for element in template.iter(XSL + "element"):
                values = {attribute.get("name"): attribute.text
                          for attribute in element.iter(XSL + "attribute")}
                pairs.append((values["Name"], values.get("Value")))
            return pairs

        expansion = one(classification="parameter-expansion")
        self.assertEqual(created("v2tov21.xslt", expansion["ordinal"])[1:], list(portable._V2_EXPANSION))
        addition = one(classification="namespace-parameter-addition")
        self.assertEqual(created("v2tov21.xslt", addition["ordinal"]),
                         [*portable._NEO_ADDED, *portable._DLT_ADDED])
        wireless = one(classification="parameter-addition")
        self.assertEqual(created("v21tov22.xslt", wireless["ordinal"]), list(portable._WIRELESS_ADDED))
        for row, (_, _, replacement) in zip(rows(classification="firmware-rename"),
                                            portable._FIRMWARE_RENAMES):
            template = ET.parse(transform / "v21tov22.xslt").getroot().findall(XSL + "template")[
                row["ordinal"] - 1]
            element, = template.iter(XSL + "element")
            self.assertEqual((element.get("name"), element.text), ("FirmwareVersion", replacement))


if __name__ == "__main__":
    unittest.main()
