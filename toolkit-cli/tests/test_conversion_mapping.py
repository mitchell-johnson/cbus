"""Offline checks for the independent CONVERTUNIT mapping-table model.

All tables, specifications and catalogues here are synthetic. Expected values
are derived by hand from the rule definitions, not from a C-Gate response.
"""
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from cbus_toolkit.conversion_mapping import (COMPATIBLE_TARGETS, MappingError, MappingTable, Rule, admitted_pairs,
                                             apply_rules, compatible, convert_parameters, expected_identity,
                                             load_catalog, session_default)
from cbus_toolkit.unitspec import UnitSpecStore


ROOT = Path(__file__).resolve().parents[1]
COPYRIGHT = "(C) CLIPSAL INTEGRATED SYSTEMS 2003 all rights reserved\n"
TABLE = COPYRIGHT + """<?xml version="1.0" encoding="UTF-8"?>
<UnitConversions>
  <UnitConversion index="1">
    <Unit_type_New>DIMDD4</Unit_type_New><Unit_type_Old>DIMDN4</Unit_type_Old>
    <Parameters>
      <Pair old="GroupAddress" new="Ch1GroupAddress"><rules><rule param1="1" param2="$FF">extractByte</rule></rules></Pair>
      <Pair old="Levels" new="Levels"><rules><rule>channelProperties</rule></rules></Pair>
      <Pair old="Maximum" new="Maximum"><rules><rule>resetToZero</rule></rules></Pair>
      <Pair old="Keep" new="Keep"><rules><rule>setDefaultValue</rule></rules></Pair>
      <Pair old="Toggle" new="ToggleDisable"><rules><rule param1="" param2="">toggleGlobalParam</rule></rules></Pair>
      <Pair old="Empty" new="Empty"><rules></rules></Pair>
    </Parameters>
  </UnitConversion>
  <UnitConversion index="2">
    <Unit_type_New>DIMDD4</Unit_type_New><Unit_type_Old>DIMDN4</Unit_type_Old>
    <Parameters><Pair old="Keep" new="Keep"><rules><rule>resetToZero</rule></rules></Pair></Parameters>
  </UnitConversion>
</UnitConversions>
"""


def spec(unit_type, params, include=None):
    rows = []
    for name, kind, size, default in params:
        extra = f"<ArraySize>{size}</ArraySize>" if size != 1 else ""
        extra += f"<DefaultValue>{default}</DefaultValue>" if default is not None else ""
        rows.append(f"<Param><Name>{name}</Name><Type>{kind}</Type><Address>$10</Address>{extra}</Param>")
    includes = f"<Includes><Include>{include}</Include></Includes>" if include else ""
    return (f'<?xml version="1.0"?><UnitSpecification><Type>{unit_type}</Type>{includes}'
            f"<Parameters>{''.join(rows)}</Parameters></UnitSpecification>")


class Fixture:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        (self.path / "ConvertUnitMappingTable.xml").write_text(TABLE)
        (self.path / "DIMDD4.xml").write_text(spec("DIMDD4", [
            ("Ch1GroupAddress", "int", 1, "$FF"), ("Levels", "int", 4, "$01 $02 $03 $04"),
            ("Maximum", "int", 2, "$FF $FF"), ("Keep", "int", 1, "$04"), ("ToggleDisable", "bit", 1, "0"),
            ("Empty", "int", 1, "$07"), ("UnitName", "sixbit", 8, "newunit"), ("Copied", "int", 1, "$09"),
            ("NoDefault", "int", 1, None)]))
        self.store = UnitSpecStore(self.path)
        self.table = MappingTable.load(self.path / "ConvertUnitMappingTable.xml")


class RuleTests(unittest.TestCase):
    def rule(self, name, old, baseline, param1=None, param2=None, param3=None, source=()):
        return apply_rules([Rule(name, param1, param2, param3)], old, baseline, list(source))

    def test_extract_and_length_rules(self):
        self.assertEqual(self.rule("extractByte", ["0x1 0x2 0x3"], "0xff", "1"), "0x2")
        self.assertEqual(self.rule("extractByte", ["0x1"], "0xff", "4"), "0xff")
        self.assertEqual(self.rule("extractByte", [], "0xff", "0"), "0xff")
        self.assertEqual(self.rule("extractByte", ["0x1"], "0xff", ""), "")
        self.assertEqual(self.rule("channelProperties", ["0x9 0x8 0x7"], "0x1 0x2"), "0x9 0x8")
        self.assertEqual(self.rule("channelProperties", ["0x9"], "0x1 0x2 0x3"), "0x9 0x2 0x3")
        # Equal lengths produce an empty result, so the native PP is omitted.
        self.assertEqual(self.rule("channelProperties", ["0x9 0x8"], "0x1 0x2"), "")
        self.assertEqual(self.rule("channelProperties", [], "0x1 0x2"), "0x1 0x2")
        self.assertEqual(self.rule("resetToZero", ["0x9 0x8 0x7"], "0x1 0x2"), "0x0 0x0")
        self.assertEqual(self.rule("resetToZero", ["0x9"], "0x1 0x2 0x3"), "0x0 0x2 0x3")
        self.assertEqual(self.rule("resetToZero", ["0x9 0x8"], "0x1 0x2"), "")
        self.assertEqual(self.rule("setDefaultValue", ["0x9"], "0x4"), "0x4")
        self.assertEqual(self.rule("changePropertyName", ["0x9 0x8"], "0x4"), "0x9")
        self.assertEqual(self.rule("changePropertyName", [], "0x4"), "0x4")
        self.assertEqual(self.rule("mapTurnOnThreshold", ["0x9 0x8"], "0x4", "1"), "0x8")

    def test_bit_index_and_toggle_rules(self):
        self.assertEqual(self.rule("oneBitToThreeBitAndInverse", ["0x0 0x1"], "0 0 0", "1", "0"), "0 0 0")
        self.assertEqual(self.rule("oneBitToThreeBitAndInverse", ["0x0 0x1"], "0 0 0", "0", "2"), "0 0 1")
        self.assertEqual(self.rule("oneBitToThreeBitAndInverse", [], "0 0 0", "0", "0"), "1 0 0")
        self.assertEqual(self.rule("mapToIndex", ["0 1 1 0"], "0 0 0 1", "1", "2"), "0 0 1 1")
        self.assertEqual(self.rule("mapToIndex", ["0"], "0 0 0 1", "3", "2"), "0 0 0 1")
        self.assertEqual(self.rule("mapThreeParamToOne", ["0x1 0x0", "0x0 0x0", "0x1 0x1"], "0 0 0 0", "0"), "1 0 1 0")
        self.assertEqual(self.rule("toggleGlobalParam", ["1"], "0", "", ""), "0")
        self.assertEqual(self.rule("toggleGlobalParam", ["0"], "0", "", ""), "1")
        self.assertEqual(self.rule("toggleGlobalParam", [], "0", "", ""), "0")

    def test_two_byte_hex_forms(self):
        self.assertEqual(self.rule("mapTo2Byte", ["0x3 0x46 0x5a 0xff"], "0xff 0xff", "0"), "0x3 0x0")
        self.assertEqual(self.rule("mapTo2Byte", ["0x3 0x46 0x5a 0xff"], "0xff 0xff", "1"), "0xa0 0x0")
        self.assertEqual(self.rule("mapTo2Byte", ["0x3 0x46 0x5a 0xff"], "0xff 0xff", "2"), "0x68 0x1")
        self.assertEqual(self.rule("mapTo2Byte", ["0x3 0x46 0x5a 0xff"], "0xff 0xff", "3"), "0xda 0x7")
        self.assertEqual(self.rule("mapTo2Byte", ["0x3"], "0xff 0xff", "3"), "0xff 0xff")
        source = [("RestrikeChannel", "0x0 0x1"), ("RestrikeDelay", "0x7")]
        self.assertEqual(self.rule("mapRestrikeDelay", ["0x0 0x1"], "0x0 0x0", "1", "RestrikeDelay", source=source), "0x46 0x0")
        self.assertEqual(self.rule("mapRestrikeDelay", ["0x0 0x1"], "0x0 0x0", "0", "RestrikeDelay", source=source), "0x0 0x0")
        # A zero delay yields Java's one-digit "0", which is not a two-byte value.
        zero = [("RestrikeChannel", "0x0 0x1"), ("RestrikeDelay", "0x0")]
        self.assertEqual(self.rule("mapRestrikeDelay", ["0x0 0x1"], "0x0 0x0", "1", "RestrikeDelay", source=zero), "0")

    def test_dimmer_profile_error_and_interlock_rules(self):
        source = [("RestrikeChannel", "0x1 0x0"), ("RestrikeDelay", "0x7")]
        self.assertEqual(self.rule("convertDimChProfileData", ["0x7"], "0xb8 0xb", "0", "RestrikeChannel", "0xb0 0x4", source), "0xb0 0x4")
        # round(7 / 62.195 * 100) = 11, rendered by Java as the bare digit "b".
        self.assertEqual(self.rule("convertDimChProfileData", ["0x7"], "0x0 0x0", "0", "RestrikeChannel", "OldUnitValue", source), "b")
        self.assertEqual(self.rule("convertDimChProfileData", ["0xff"], "0x0 0x0", "0", "RestrikeChannel", "OldUnitValue", source), "0x9a 0x1")
        self.assertEqual(self.rule("convertDimChProfileData", ["0x7"], "0x0 0x0", "1", "RestrikeChannel", "OldUnitValue", source), "0x0 0x0")
        for index, expected in enumerate(("0 0 1", "1 0 1", "0 1 1", "1 1 1")):
            self.assertEqual(self.rule("convertDimChannelProfileSelection", ["0x1 0x1 0x1 0x1"], "0 0 0", str(index)), expected)
        self.assertEqual(self.rule("convertDimChannelProfileSelection", ["0x0 0x1"], "1 1 0", "0"), "1 1 0")
        self.assertEqual(self.rule("convertDimChannelProfileSelection", [], "1 1 0", "0"), "0 0 0")
        self.assertEqual([self.rule("convertErrorReportInterval", [f"0x{n}"], "0x5", "", "") for n in range(0, 9)],
                         ["", "0x1", "0x1", "0x1", "0x1", "0x1", "0x2", "0x4", ""])
        self.assertEqual(self.rule("mapInterlockMask", ["0x2"], "0xff 0xff", "", "1"), "0x7 0x0")
        self.assertEqual(self.rule("mapInterlockMask", ["0x2"], "0xff 0xff", "", "3"), "0xff 0xff")
        self.assertEqual(self.rule("mapInterlockMask", ["0x9"], "0xff 0xff", "", "3"), "")
        # 15 - 2 + 1 = 14 = 0b1110, reversed into four bit tokens.
        self.assertEqual(self.rule("mapInterlockPriority", ["0x2"], "1 1 1 1", "15", "1"), "0 1 1 1")
        self.assertEqual(self.rule("mapInterlockPriority", ["0x2"], "1 1 1 1", "15", "3"), "1 1 1 1")

    def test_last_rule_wins_and_every_rule_sees_baseline(self):
        rules = [Rule("extractByte", "0"), Rule("setDefaultValue")]
        self.assertEqual(apply_rules(rules, ["0x9"], "0x4", []), "0x4")
        self.assertIsNone(apply_rules([], ["0x9"], "0x4", []))

    def test_rule_failures_are_explicit(self):
        with self.assertRaises(MappingError):
            self.rule("mapThreeParamToOne", ["0x1"], "0 0", "3")
        with self.assertRaises(MappingError):
            self.rule("mapTurnOnThreshold", ["0x1"], "0", "3")
        with self.assertRaises(MappingError):
            self.rule("oneBitToThreeBitAndInverse", ["0x2"], "0 0 0", "0", "0")


class TableTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture()
        self.addCleanup(self.fixture.tmp.cleanup)

    def test_admission_matches_source_pinned_table(self):
        self.assertEqual(len(admitted_pairs()), 15)
        self.assertTrue(compatible("DIMDN4", "DIMDN4"))
        self.assertTrue(compatible("dimdn4", "DIMDU4"))
        # dg folds only the source key; target membership is case-sensitive.
        self.assertFalse(compatible("DIMDN4", "dimdu4"))
        self.assertFalse(compatible("DIMDD4", "DIMDN4"))
        self.assertFalse(compatible("RELDN4A", "RELDN4"))
        self.assertFalse(compatible("DIMDN4", "RELDN4A"))
        self.assertEqual(set(COMPATIBLE_TARGETS["DIMDU4"]), {"DIMDN8", "DIMDN8F", "DIMDN4", "DIMDN4F", "DIMDD4"})

    def test_first_duplicate_entry_wins_and_unknown_rules_fail_closed(self):
        self.assertEqual(self.fixture.table.find("dimdn4", "dimdd4").index, 1)
        self.assertIsNone(self.fixture.table.find("DIMDN4", "DIMDU4"))
        self.assertEqual(len(self.fixture.table.sha256), 64)
        for text in (TABLE.replace("toggleGlobalParam", "executeRule"),
                     TABLE.replace("UnitConversions>", "Other>"),
                     COPYRIGHT + '<!DOCTYPE x [<!ENTITY a "b">]><UnitConversions/>'):
            path = self.fixture.path / "bad.xml"
            path.write_text(text)
            with self.subTest(text=text[60:90]), self.assertRaises(MappingError):
                MappingTable.load(path)

    def test_session_defaults_use_native_value_rendering(self):
        target = self.fixture.store.load("DIMDD4.xml")
        self.assertEqual(session_default(target.get("Levels")), "0x1 0x2 0x3 0x4")
        self.assertEqual(session_default(target.get("ToggleDisable")), "0")
        self.assertEqual(session_default(target.get("UnitName")), "NEWUNIT ")
        self.assertEqual(session_default(target.get("NoDefault")), "")

    def test_conversion_orders_rules_fallbacks_and_omissions(self):
        target = self.fixture.store.load("DIMDD4.xml")
        source = [("GroupAddress", "0x1 0x2 0x3"), ("Levels", "0x9 0x8 0x7 0x6"), ("Maximum", "0xc8"),
                  ("Keep", "0x2"), ("Toggle", "1"), ("Empty", "0x3"), ("UnitName", "CONVA   "), ("Copied", "")]
        self.assertEqual(convert_parameters(self.fixture.table, "DIMDN4", source, target), [
            ("Ch1GroupAddress", "0x2"), ("Maximum", "0x0 0xff"), ("Keep", "0x4"), ("ToggleDisable", "0"),
            ("UnitName", "CONVA   "), ("Copied", "0x9")])
        # Without stored source PP, rules are skipped and only defaults remain.
        self.assertEqual(convert_parameters(self.fixture.table, "DIMDN4", [], target), [
            ("Ch1GroupAddress", "0xff"), ("Levels", "0x1 0x2 0x3 0x4"), ("Maximum", "0xff 0xff"), ("Keep", "0x4"),
            ("ToggleDisable", "0"), ("Empty", "0x7"), ("UnitName", "NEWUNIT "), ("Copied", "0x9")])
        # A same-type conversion copies the stored list verbatim.
        self.assertEqual(convert_parameters(self.fixture.table, "DIMDD4", source, target), source)

    def test_identity_and_regenerated_channels(self):
        catalog_path = self.fixture.path / "cbusunits.xml"
        catalog_path.write_text("""<CBusUnits><Units>
          <Unit><CatalogNumber>5504D2D</CatalogNumber><FirmwareRevisions>
            <Revision><UnitType>DIMDD4</UnitType><MinVersion>1.3.0</MinVersion><MaxVersion>1.3.0</MaxVersion>
              <UnitSpecName>DIMDD4.xml</UnitSpecName><ClassName>CBus3DinDigDimmerUnit</ClassName><IsDefault>true</IsDefault></Revision>
          </FirmwareRevisions><OutputCount>4</OutputCount></Unit>
          <Unit><CatalogNumber>L5504D2U</CatalogNumber><FirmwareRevisions>
            <Revision><UnitType>DIMDU4</UnitType><MinVersion>2.7.00</MinVersion><MaxVersion>2.7.00</MaxVersion>
              <UnitSpecName>DIMDU4.xml</UnitSpecName><ClassName>CBusUniversalDimmer</ClassName><IsDefault>true</IsDefault></Revision>
          </FirmwareRevisions><OutputCount>4</OutputCount></Unit></Units></CBusUnits>""")
        catalog = load_catalog(catalog_path)
        source = {"TagName": "Old", "UnitName": "Name", "Address": "20", "SerialNumber": "1.2", "UnitType": "DIMDN4"}
        one = expected_identity(mode=1, source=source, destination=None, target_type="DIMDD4",
                                catalog_number="5504D2D", catalog=catalog)
        self.assertEqual(one["SerialNumber"], "00000000.0000")
        self.assertEqual((one["FirmwareVersion"], one["TagName"], one["Address"]), ("1.3.0", "Old", "20"))
        self.assertEqual(one["OutputChannels"], [{"Address": str(n), "TagName": f"Channel{n}"} for n in range(1, 5)])
        destination = {"TagName": "New", "UnitName": "Dest", "Address": "21", "SerialNumber": "7.8",
                       "UnitType": "DIMDU4", "FirmwareVersion": "2.7.00", "CatalogNumber": "L5504D2U"}
        two = expected_identity(mode=2, source=source, destination=destination, target_type="DIMDU4",
                                catalog_number=None, catalog=catalog)
        self.assertEqual({key: two[key] for key in ("TagName", "Address", "SerialNumber", "UnitType")},
                         {"TagName": "New", "Address": "21", "SerialNumber": "7.8", "UnitType": "DIMDU4"})
        self.assertEqual(two["OutputChannels"], [])


RECEIPT = ROOT / "research/fixtures/convertunit-pairs-native-receipt.json"
RECEIPT_SHA256 = "a57da911206b6270d678ae05bc90cdcd9ecf85c0006862993f4a08f599d50f5d"


class ReceiptTests(unittest.TestCase):
    def test_committed_native_receipt_covers_every_admitted_pair(self):
        raw = RECEIPT.read_bytes()
        self.assertEqual(sha256(raw).hexdigest(), RECEIPT_SHA256)
        receipt = json.loads(raw)
        self.assertEqual(receipt["format"], "cbus-convertunit-pairs-receipt-v1")
        self.assertEqual(receipt["backend"]["backend"], "native")
        covered = {(row["source_type"], row["target_type"], row["mode"]) for row in receipt["cases"]}
        self.assertEqual(covered, {(s, t, m) for s, t in admitted_pairs() for m in (1, 2)})
        self.assertTrue(all(row["passed"] for row in
                            [*receipt["cases"], *receipt["negative_cases"], *receipt["boundary_cases"]]))
        for name in ("ConvertUnitMappingTable.xml", "cbusunits.xml", "DIMDU4.xml", "RELDN16A.xml"):
            self.assertRegex(receipt["inputs"][name], "^[0-9a-f]{64}$")
        self.assertNotIn("/Volumes", json.dumps(receipt))


if __name__ == "__main__":
    unittest.main()
