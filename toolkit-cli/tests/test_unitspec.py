"""Synthetic schema fixtures exercise the vendor-independent unit-spec reader."""
from pathlib import Path
import tempfile
import unittest

from cbus_toolkit.unitspec import UnitSpecStore, UnitCatalog, UnitSpecError, compare_versions, version_matches


def parameter(name, kind="int", *, default="0", extra="", address="$20"):
    return f"<Param><Name>{name}</Name><Type>{kind}</Type><Address>{address}</Address><Protection>checksum</Protection><DefaultValue>{default}</DefaultValue>{extra}</Param>"


def specification(name, parameters="", includes="", extra=""):
    return f'<UnitSpecification><Type>"{name}"</Type><MinVersion>1.2.0</MinVersion><MaxVersion>9</MaxVersion>{extra}<Includes>{includes}</Includes><Parameters>{parameters}</Parameters></UnitSpecification>'


class UnitSpecTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.write("base.xml", specification("BASE", parameter("Address", extra="<MinValue>0</MinValue><MaxValue>$FF</MaxValue>") + parameter("Name", "sixbit", default="FIRST   ", extra="<ArraySize>8</ArraySize>") + parameter("Output", extra="<Description>old</Description><Tag>output</Tag>")))
        self.write("device.xml", specification("DEVICE", parameter("Output", default="$03", extra="<BitSize>3</BitSize><Tag>Light</Tag><Tag>Output</Tag>") + parameter("Groups", default="$01 $02", extra="<ArraySize>2</ArraySize><ArraySkip>1</ArraySkip>") + parameter("Bits", "Bit", default="0 1", extra="<ArraySize>2</ArraySize><BitAddress>7</BitAddress>") + parameter("Text", "string", default="hello", extra="<ArraySize>8</ArraySize>"), includes="<Include>base.xml</Include>"))
        self.store = UnitSpecStore(self.root)
        self.spec = self.store.load("device.xml")

    def write(self, filename, body):
        (self.root / filename).write_text(body)

    def test_recursive_include_order_whole_parameter_override_and_provenance(self):
        self.assertEqual(self.spec.sources, ("base.xml", "device.xml"))
        self.assertEqual(list(self.spec.parameters), ["Address", "Name", "Output", "Groups", "Bits", "Text"])
        self.assertEqual(self.spec.get("Address").source, "base.xml")
        self.assertEqual(self.spec.get("Output").source, "device.xml")
        self.assertEqual(self.spec.get("Output").description, "")
        self.assertEqual(self.spec.overrides, ({"name": "Output", "previous_source": "base.xml", "source": "device.xml"},))

    def test_multi_level_include(self):
        self.write("third.xml", specification("THIRD", parameter("Third"), "<Include>device.xml</Include>"))
        spec = self.store.load("third.xml")
        self.assertEqual(spec.sources, ("base.xml", "device.xml", "third.xml"))
        self.assertEqual(len(spec.parameters), 7)

    def test_duplicate_or_cyclic_include_rejected(self):
        self.write("duplicate.xml", specification("DUP", includes="<Include>base.xml</Include><Include>device.xml</Include>"))
        self.write("cyclic.xml", specification("CYCLE", includes="<Include>cyclic.xml</Include>"))
        for name in ("duplicate.xml", "cyclic.xml"):
            with self.subTest(name=name), self.assertRaises(UnitSpecError):
                self.store.load(name)

    def test_include_path_containment_missing_and_symlink(self):
        for name in ("../outside.xml", "/etc/passwd", "..\\outside.xml", "missing.xml"):
            with self.subTest(name=name), self.assertRaises(UnitSpecError):
                self.store.load(name)
        (self.root / "linked.xml").symlink_to("/etc/passwd")
        with self.assertRaises(UnitSpecError):
            self.store.load("linked.xml")

    def test_authenticated_copyright_preamble_and_plain_xml(self):
        body = specification("PRE", parameter("One"))
        self.write("preamble.xml", "(C) CLIPSAL INTEGRATED SYSTEMS 2003 all rights reserved\n" + body)
        self.assertEqual(self.store.load("preamble.xml").unit_type, "PRE")
        self.write("garbage.xml", "untrusted preamble\n" + body)
        with self.assertRaises(UnitSpecError):
            self.store.load("garbage.xml")

    def test_namespace_and_legacy_unitspec_root(self):
        body = specification("OLD", parameter("One")).replace("UnitSpecification", "UnitSpec").replace("<UnitSpec>", '<UnitSpec xmlns="urn:spec">')
        self.write("old.xml", body)
        self.assertEqual(self.store.load("old.xml").get("One").address, 32)

    def test_metadata_tags_and_structural_defaults(self):
        parameter = self.spec.get("Address").as_dict()
        self.assertEqual(parameter["array_size"], 1)
        self.assertEqual(parameter["bit_size"], 8)
        self.assertEqual(parameter["bit_address"], 0)
        self.assertEqual(parameter["array_skip"], 0)
        self.assertEqual([p["name"] for p in self.spec.list_parameters(tags=["LIGHT"])], ["Output"])
        self.assertEqual(self.spec.as_dict(include_parameters=False)["parameter_count"], 6)

    def test_defaults_preserve_text_whitespace_and_numeric_notation(self):
        defaults = self.spec.defaults()
        self.assertEqual(defaults["Name"], "FIRST   ")
        self.assertEqual(defaults["Groups"], "$01 $02")
        self.assertTrue(all(result["valid"] for result in self.spec.validate_defaults()))

    def test_integer_decimal_hex_width_and_bounds_validation(self):
        self.assertEqual(self.spec.validate_value("Address", "$fF")["parsed"], 255)
        self.assertEqual(self.spec.validate_value("Address", "0x0F")["parsed"], 15)
        self.assertEqual(self.spec.validate_value("Address", "010")["parsed"], 10)
        for value in (-1, 256, "not-number", 1.0, True):
            with self.subTest(value=value):
                self.assertFalse(self.spec.validate_value("Address", value)["valid"])
        self.assertFalse(self.spec.validate_value("Output", 8)["valid"])
        self.assertTrue(self.spec.validate_value("Output", 7)["valid"])

    def test_arrays_require_full_values_unless_partial_explicit(self):
        self.assertTrue(self.spec.validate_value("Groups", [1, 2])["valid"])
        self.assertFalse(self.spec.validate_value("Groups", [1])["valid"])
        self.assertFalse(self.spec.validate_value("Groups", [1, 2, 3], allow_partial=True)["valid"])
        self.assertFalse(self.spec.validate_value("Groups", [], allow_partial=True)["valid"])
        partial = self.spec.validate_value("Groups", "3", allow_partial=True)
        self.assertTrue(partial["valid"])
        self.assertEqual(partial["parsed"], [3])
        self.assertTrue(partial["warnings"])

    def test_bit_case_normalization_and_value_validation(self):
        self.assertEqual(self.spec.get("Bits").type, "bit")
        self.assertTrue(self.spec.validate_value("Bits", "1 0")["valid"])
        self.assertFalse(self.spec.validate_value("Bits", "2 0")["valid"])

    def test_string_and_sixbit_validation_never_encodes_or_coerces(self):
        self.assertTrue(self.spec.validate_value("Name", "unit")["valid"])
        self.assertEqual(self.spec.validate_value("Name", "unit")["parsed"], "unit")
        self.assertFalse(self.spec.validate_value("Name", "nine chars")["valid"])
        self.assertFalse(self.spec.validate_value("Name", "🙂")["valid"])
        self.assertFalse(self.spec.validate_value("Name", "x\n")["valid"])
        self.assertTrue(self.spec.validate_value("Name", "?")["warnings"])
        self.assertFalse(self.spec.validate_value("Text", "123456789")["valid"])
        self.assertFalse(self.spec.validate_value("Text", "nul\x00")["valid"])
        self.assertTrue(self.spec.validate_value("Text", "é")["warnings"])
        self.assertFalse(self.spec.validate_value("Text", 5)["valid"])

    def test_unknown_types_are_visible_but_not_validated_as_known(self):
        self.write("future.xml", specification("FUTURE", parameter("Thing", "future", extra="<Custom>preserved</Custom>")))
        spec = self.store.load("future.xml")
        self.assertEqual(spec.get("Thing").fields["Custom"], "preserved")
        self.assertFalse(spec.validate_value("Thing", "value")["valid"])

    def test_long_parameter_declared_width(self):
        self.write("long.xml", specification("LONG", parameter("Value", "long", extra="<BitSize>32</BitSize>")))
        spec = self.store.load("long.xml")
        self.assertTrue(spec.validate_value("Value", "$FFFFFFFF")["valid"])
        self.assertFalse(spec.validate_value("Value", "$100000000")["valid"])

    def test_missing_parameters_and_bad_structure_raise_clear_errors(self):
        with self.assertRaises(UnitSpecError):
            self.spec.get("MISSING")
        for body in ("<Other/>", specification("BAD", "<Param><Name>X</Name></Param>"), specification("BAD", parameter("X", extra="<ArraySize>0</ArraySize>")), specification("BAD", parameter("X", extra="<BitSize>65</BitSize>")), specification("BAD", parameter("X", extra="<BitAddress>-1</BitAddress>"))):
            self.write("bad.xml", body)
            with self.subTest(body=body), self.assertRaises(UnitSpecError):
                self.store.load("bad.xml")

    def test_doctype_and_entities_rejected(self):
        self.write("dtd.xml", '<!DOCTYPE UnitSpecification [<!ENTITY x "x">]>' + specification("DTD"))
        with self.assertRaises(UnitSpecError):
            self.store.load("dtd.xml")

    def test_spec_inventory_excludes_conversion_tables(self):
        self.write("conversions.xml", "<UnitConversions/>")
        self.assertEqual([row["filename"] for row in self.store.list_specs()], ["base.xml", "device.xml"])

    def test_version_comparison_matches_cgate_numeric_segments(self):
        for left, right in (("1.2.0", "1.2"), ("v1.02.00", "1.2"), ("1.00", "1")):
            self.assertEqual(compare_versions(left, right), 0)
        self.assertGreater(compare_versions("1.10", "1.9"), 0)
        self.assertLess(compare_versions("1.2.63", "1.2.64"), 0)
        self.assertTrue(version_matches("1.2.0", "1.2", "1.2"))
        self.assertFalse(self.spec.supports_version("1.1"))
        self.assertTrue(self.spec.supports_version("1.2"))
        for version in ("", "unknown", "1..2"):
            with self.assertRaises(UnitSpecError):
                compare_versions(version, "1")

    def catalog(self):
        self.write("catalog.xml", '''<CBusUnits><Units><Unit><SubUnits>
          <Unit><CatalogNumber>1000</CatalogNumber><AlternativeCatalogNumbers>ALT1000;1000*</AlternativeCatalogNumbers><Description>Device</Description><FirmwareRevisions>
            <Revision><UnitType>DEVICE</UnitType><MinVersion>1.0</MinVersion><MaxVersion>1.9</MaxVersion><UnitSpecName>old.xml</UnitSpecName></Revision>
            <Revision><UnitType>DEVICE</UnitType><MinVersion>2.0</MinVersion><MaxVersion>2.9</MaxVersion><UnitSpecName>device.xml</UnitSpecName><IsDefault>true</IsDefault></Revision>
          </FirmwareRevisions></Unit>
          <Unit><CatalogNumber>2000</CatalogNumber><FirmwareRevisions><Revision><UnitType>FUT*</UnitType><MinVersion>2</MinVersion><MaxVersion>9</MaxVersion><UnitSpecName>future.xml</UnitSpecName></Revision></FirmwareRevisions></Unit>
        </SubUnits></Unit></Units></CBusUnits>''')
        return UnitCatalog.load(self.root / "catalog.xml")

    def test_catalog_revision_type_firmware_and_alternative_matching(self):
        catalog = self.catalog()
        self.assertEqual(len(catalog.records), 3)
        match = catalog.match(unit_type="DEVICE", firmware="2.0", catalog_number="ALT1000")
        self.assertEqual(len(match), 1)
        self.assertTrue(match[0]["default"])
        self.assertEqual(catalog.select_spec(unit_type="DEVICE", firmware="1.5", catalog_number="1000"), "old.xml")
        self.assertEqual(catalog.select_spec(unit_type="DEVICE", firmware="2.5", catalog_number="1000WH"), "device.xml")
        self.assertEqual(catalog.select_spec(unit_type="FUTURE", firmware="2.5"), "future.xml")
        self.assertEqual(catalog.match(unit_type="DEVICE", firmware="2.5", catalog_number="UNKNOWN"), [])
        with self.assertRaises(UnitSpecError):
            catalog.select_spec(unit_type="UNKNOWN", firmware="2.5")

    def test_catalog_ambiguous_spec_selection_is_rejected(self):
        catalog = self.catalog()
        extra = dict(catalog.records[1], spec_filename="different.xml")
        catalog.records.append(extra)
        with self.assertRaises(UnitSpecError):
            catalog.select_spec(unit_type="DEVICE", firmware="2.1")

    def test_wrong_catalog_root_is_rejected(self):
        with self.assertRaises(UnitSpecError):
            UnitCatalog.load(self.root / "device.xml")


if __name__ == "__main__":
    unittest.main()
