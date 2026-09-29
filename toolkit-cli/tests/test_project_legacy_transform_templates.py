"""Offline goldens for the Unit-conditioned legacy migration templates.

Each case is synthetic. The owned native receipt covers the same branches
against original C-Gate TRANSFORM PROJECT bytes.
"""
from __future__ import annotations

import unittest

from cbus_toolkit.project_legacy_transform import (
    LegacyProjectTransformError, transform_repaired_legacy_project,
)


HEAD = b'<?xml version="1.0" encoding="utf-8"?><Installation><DBVersion>'
CIS = b'xmlns:cis="http://www.clipsal.com/cis/schema/2001/cbus.xsd"'
FF4 = b"0xff 0xff 0xff 0xff"


def document(version: str, *units: bytes) -> bytes:
    return (HEAD + version.encode() + b'</DBVersion><Project><Address>LEGACY</Address><Network>'
            + b"\n".join(units) + b'</Network></Project></Installation>\n')


def expected(version: str, *units: bytes) -> bytes:
    return document(version, *units).replace(
        b'<DBVersion>' + version.encode() + b'</DBVersion>', b'<DBVersion>2.3</DBVersion>', 1)[:-1]


def unit(unit_type: str, firmware: str, body: bytes = b"", *, tag: bytes = b"Unit",
         attributes: bytes = b"") -> bytes:
    return (b"<" + tag + attributes + b"><TagName>U</TagName><UnitType>" + unit_type.encode()
            + b"</UnitType><FirmwareVersion>" + firmware.encode() + b"</FirmwareVersion>"
            + b"<CatalogNumber>X</CatalogNumber>" + body + b"</" + tag + b">")


def pp(name: str, value: str = "1") -> bytes:
    return f'<PP Name="{name}" Value="{value}"/>'.encode()


class LegacyTemplateGoldenTests(unittest.TestCase):
    def convert(self, source: bytes):
        return transform_repaired_legacy_project(source)

    def test_pc_and_pci_firmware_rename_moves_the_element_last(self):
        for version in ("2", "2.1"):
            for unit_type, firmware in (("PC_CTA", "4.00"), ("PC_CTA", "4.00.3"),
                                        ("PCINT4", "4.0.00"), ("PCLOCAL4", "4.0.00"),
                                        ("PC_CBTI", "4.0.00.7"), ("PC_PGA", "4.0.00"),
                                        ("PC_IRT2", "4.0.00"), ("PC_WHAM", "4.0.00")):
                with self.subTest(version=version, unit_type=unit_type, firmware=firmware):
                    body = pp("Keep") + pp("Remote3Identity")
                    result = self.convert(document(version, unit(unit_type, firmware, body)))
                    moved = (b"<Unit><TagName>U</TagName><UnitType>" + unit_type.encode()
                             + b"</UnitType><CatalogNumber>X</CatalogNumber>" + pp("Keep")
                             + b"<FirmwareVersion>4.0.0</FirmwareVersion></Unit>")
                    self.assertEqual(result.transformed_xml, expected(version, moved))
                    self.assertEqual(result.firmware_version_changes, ((unit_type, firmware, "4.0.0"),))
                    self.assertEqual(result.removed_programming_parameters, ("Remote3Identity",))
                    self.assertEqual(result.as_dict()["firmware_version_changes"],
                                     [{"unit_type": unit_type, "from": firmware, "to": "4.0.0"}])

    def test_rename_prefixes_types_and_version_bound(self):
        for version, unit_type, firmware in (("2.1", "PC_CTA", "4.0.0"), ("2.1", "PC_CTA", "4.0.00"),
                                             ("2.1", "PCINT4", "4.00"), ("2.1", "PC_PGA", "4.0.0"),
                                             ("2.1", "PC_DAL2", "4.0.00"), ("2.2", "PC_CTA", "4.00")):
            with self.subTest(version=version, unit_type=unit_type, firmware=firmware):
                source = document(version, unit(unit_type, firmware))
                result = self.convert(source)
                self.assertEqual(result.transformed_xml, expected(version, unit(unit_type, firmware)))
                self.assertEqual(result.firmware_version_changes, ())

    def test_dlt_corridor_link_is_removed_only_without_application(self):
        for version in ("2", "2.1"):
            for unit_type in ("KEYBL5", "KEYML5"):
                with self.subTest(version=version, unit_type=unit_type):
                    bare = unit(unit_type, "1.0", pp("CorridorLinkEnable", "0") + pp("Other", "2"))
                    applied = unit(unit_type, "1.0", pp("Application", "0x38") + pp("CorridorLinkEnable", "0"))
                    result = self.convert(document(version, bare, applied))
                    self.assertEqual(result.transformed_xml,
                                     expected(version, bare.replace(pp("CorridorLinkEnable", "0"), b""), applied))
                    self.assertEqual(result.removed_programming_parameters, ("CorridorLinkEnable",))

    def test_neo_removal_covers_all_types_and_the_16_prefix(self):
        four = b"".join(pp(name) for name in ("KeyDisableGroupInvert", "CorridorLinkEnable",
                                              "NightlightColour", "DisableIRNEC"))
        for unit_type, firmware, removed in (("KEYM8", "1.6.2", True), ("KEYAV4", "1.60", True),
                                             ("KEYA1", "1.7", False), ("KEYB6", "2.0", False)):
            with self.subTest(unit_type=unit_type, firmware=firmware):
                source_unit = unit(unit_type, firmware, four + pp("Keep"))
                result = self.convert(document("2.1", source_unit))
                output = unit(unit_type, firmware, pp("Keep")) if removed else source_unit
                self.assertEqual(result.transformed_xml, expected("2.1", output))

    def test_wireless_2_0_0_units_with_application_gain_remote_slots(self):
        added = b"".join(b'<PP Name="Remote%dIdentity" Value="' % n + FF4 + b'"/>' for n in range(3, 9))
        added += b"".join(b'<PP Name="Remote%dKeyMap" Value="' % n + FF4 + b" " + FF4 + b'"/>'
                          for n in range(3, 9))
        body = pp("Application", "0x38") + pp("Remote3Identity", "0x1") + pp("Keep")
        for version in ("2", "2.1"):
            with self.subTest(version=version):
                result = self.convert(document(version, unit("WRB4D1", "2.0.0", body),
                                               unit("WRM8R2", "2.0.0", pp("Keep")),
                                               unit("WRP6D2", "1.9", body)))
                self.assertEqual(result.transformed_xml, expected(
                    version,
                    unit("WRB4D1", "2.0.0", pp("Application", "0x38") + pp("Keep") + added),
                    unit("WRM8R2", "2.0.0", pp("Keep")),
                    unit("WRP6D2", "1.9", pp("Application", "0x38") + pp("Keep"))))
                self.assertEqual(len(result.added_programming_parameters), 12)
                self.assertEqual(result.removed_programming_parameters, ("Remote3Identity",) * 2)

    def test_cis_unit_additions_apply_only_from_version_2(self):
        neo = unit("KEYB2", "1.6", pp("FeatureSet") + pp("Remote3Identity"), tag=b"cis:Unit",
                   attributes=b" " + CIS)
        dlt = unit("KEYBL5", "1.0", tag=b"cis:Unit", attributes=b" " + CIS)
        old = unit("KEYM4", "1.5", tag=b"cis:Unit", attributes=b" " + CIS)
        neo_added = b"".join(pp(name, value) for name, value in (
            ("KeyDisableGroupInvert", "1"), ("CorridorLinkEnable", "0"),
            ("NightlightColour", "0"), ("DisableIRNEC", "1")))
        for source_unit, version, output in (
                (neo, "2", unit("KEYB2", "1.6", neo_added, tag=b"cis:Unit", attributes=b" " + CIS)),
                (neo, "2.1", unit("KEYB2", "1.6", pp("FeatureSet"), tag=b"cis:Unit", attributes=b" " + CIS)),
                (dlt, "2", unit("KEYBL5", "1.0", pp("CorridorLinkEnable", "0"), tag=b"cis:Unit",
                                attributes=b" " + CIS)),
                (dlt, "2.1", dlt), (old, "2", old)):
            with self.subTest(version=version, unit=source_unit[:40]):
                self.assertEqual(self.convert(document(version, source_unit)).transformed_xml,
                                 expected(version, output))

        two = self.convert(document("2", dlt, dlt))
        added = unit("KEYBL5", "1.0", pp("CorridorLinkEnable", "0"), tag=b"cis:Unit", attributes=b" " + CIS)
        self.assertEqual(two.transformed_xml, expected("2", added, added))

    def test_version_2_expansion_and_rename(self):
        defaults = self.convert(document("2", unit("KEYB2", "1.5", pp("KeyExtraLongPressDuration", "0x40"))))
        self.assertEqual(len(defaults.added_programming_parameters), 52)
        self.assertIn(pp("KeyExtraLongPressDuration", "0x40") + pp("KeyMaskAllowed", "0x0"),
                      defaults.transformed_xml)
        self.assertIn(pp("Key9BlockMap", "0 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0"), defaults.transformed_xml)
        self.assertTrue(defaults.transformed_xml.endswith(
            pp("Remote2KeyMap", " ".join(["0xff"] * 16)) + b"</Unit></Network></Project></Installation>"))
        source = document("2", unit("KEYA3", "1.5", pp("KeyMaskAllowed", "0x1")
                                    + pp("KeyExtraLongPressDuration", "0x40")
                                    + pp("EnableNightlightPCx", "a&amp;b")))
        result = self.convert(source)
        self.assertEqual(result.removed_programming_parameters, ("KeyMaskAllowed",))
        self.assertEqual(result.renamed_programming_parameters,
                         (("EnableNightlightPCx", "EnableNightlightOnPCx"),))
        self.assertIn(pp("EnableNightlightOnPCx", "a&amp;b"), result.transformed_xml)
        self.assertNotIn(pp("KeyMaskAllowed", "0x1"), result.transformed_xml)
        at_21 = source.replace(b"<DBVersion>2</DBVersion>", b"<DBVersion>2.1</DBVersion>")
        self.assertEqual(self.convert(at_21).transformed_xml,
                         at_21.replace(b"<DBVersion>2.1</DBVersion>", b"<DBVersion>2.3</DBVersion>")[:-1])

    def test_stage_one_output_precedes_unit_end_additions(self):
        long_press = pp("KeyExtraLongPressDuration", "0x40")
        source = document("2", unit("KEYB2", "1.6", long_press, tag=b"cis:Unit", attributes=b" " + CIS),
                          unit("WRB2D1", "2.0.0", pp("Application", "0x38") + long_press))
        result = self.convert(source).transformed_xml
        remote2 = pp("Remote2KeyMap", " ".join(["0xff"] * 16))
        first = result.index(b"<cis:Unit")
        self.assertLess(result.index(remote2, first), result.index(pp("KeyDisableGroupInvert"), first))
        second = result.index(b"<Unit>", first)
        self.assertLess(result.index(remote2, second),
                        result.index(pp("Remote3Identity", "0xff 0xff 0xff 0xff"), second))

    def test_unreproducible_shapes_are_rejected(self):
        cis = unit("KEYB2", "1.6", tag=b"cis:Unit", attributes=b" " + CIS)
        invalid = (
            document("2", cis).replace(b"<Installation>", b"<Installation " + CIS + b">").replace(
                b"<cis:Unit " + CIS + b">", b"<cis:Unit>"),
            document("2", cis).replace(b"<Network>", b"<Network " + CIS + b">"),
            document("2", unit("KEYB2", "1.6", tag=b"x:Unit", attributes=b' xmlns:x="urn:x"')),
            document("2.1", unit("PC_CTA", "4.00", attributes=b' Extra="1"')),
            document("2.1", unit("PC_CTA", "4.00")).replace(
                b"<FirmwareVersion>4.00</FirmwareVersion>", b"<FirmwareVersion>4.00<!--x--></FirmwareVersion>"),
            document("2.1", unit("PC_CTA", "4.00")).replace(b"<Network>", b"<Network><!--<Unit>-->"),
            document("2.1", unit("PC_CTA", "4.00 beta")),
            document("2.1", unit("PC_CTA", "4.00")).replace(b"<FirmwareVersion>4.00</FirmwareVersion>", b""),
            document("2.1", unit("PC_CTA", "4.00", b"<Group><Unit/></Group>")),
        )
        for source in invalid:
            with self.subTest(source=source):
                with self.assertRaises(LegacyProjectTransformError):
                    self.convert(source)


if __name__ == "__main__":
    unittest.main()
