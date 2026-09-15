from dataclasses import replace
import os
from pathlib import Path
import struct
import unittest
from uuid import uuid4
import xml.etree.ElementTree as ET

from cbus_toolkit.offline_conversion import OfflineConversion, ConversionError, ConversionApplyError, COPY_PARAMETERS
from cbus_toolkit.memory import MemoryCodec, MemoryImage
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec, UnitSpecStore


def fixture(unit_type):
    # Synthetic mask1 fixture. Values are chosen for tests, not hardware dumps.
    rows = [
        ("LightIndex", "int", 0, 1, 8, 0, 0), ("LightLevel", "int", 1, 16, 8, 0, 0),
        ("LightLevelStore1", "int", 17, 4, 8, 0, 0), ("LightLevelStore2", "int", 21, 4, 8, 0, 0),
        ("EEPROMChecksumActive", "int", 30, 1, 8, 0, 0), ("EEPROMChecksum", "int", 31, 1, 8, 0, 0),
        ("UnitAddress", "int", 32, 1, 8, 0, 0), ("Application", "int", 33, 2, 8, 0, 0),
        ("Project", "sixbit", 35, 8, 8, 0, 0), ("NetworkAddress", "int", 41, 1, 8, 0, 0),
        ("UnitName", "sixbit", 42, 8, 8, 0, 0), ("DebounceTime", "int", 48, 1, 6, 0, 0),
        ("LongPressTime", "int", 49, 1, 6, 0, 0), ("JPCommand", "int", 50, 4, 4, 4, 1),
        ("SRCommand", "int", 50, 4, 4, 0, 1), ("LPCommand", "int", 51, 4, 4, 4, 1),
        ("LRCommand", "int", 51, 4, 4, 0, 1), ("BlockAllocation", "int", 58, 4, 8, 0, 0),
        ("EEPROMLevelRecall", "bit", 62, 1, 8, 0, 0), ("EEPROMLevelStore", "bit", 62, 1, 8, 1, 0),
        ("LearnMode", "bit", 62, 1, 8, 3, 0), ("LearnAnyApp", "bit", 62, 1, 8, 4, 0),
        ("LearnedFlag", "bit", 62, 1, 8, 5, 0), ("EEPROMChecksumAlarm", "bit", 62, 1, 8, 7, 0),
        ("IndicatorBrightness", "int", 63, 1, 8, 0, 0), ("RampRate", "int", 64, 2, 8, 0, 0),
        ("StatusReportInterval", "int", 66, 1, 8, 0, 0), ("AreaGroupAddress", "int", 67, 1, 8, 0, 0),
        ("TimerHighByte", "int", 68, 4, 8, 0, 0), ("TimerLowByte", "int", 72, 4, 8, 0, 0),
        ("TimerExpiryCommand", "int", 76, 4, 4, 0, 0), ("GroupAddress", "int", 80, 8, 8, 0, 0),
        ("IndicatorBlockAssignment", "int", 96, 4, 2, 0, 0), ("IndicatorFunction", "int", 96, 4, 2, 2, 0),
        ("PatchEnable", "int", 112, 2, 8, 0, 0), ("CUSTYPE", "int", 247, 8, 8, 0, 0),
    ]
    parameters = {}
    for name, kind, address, count, bits, offset, skip in rows:
        value = " ".join(["0"] * count)
        if kind == "sixbit": value = "TARGET"
        if name == "Application": value = "56 255"
        fields = dict(Name=name, Type=kind, Address=str(address), ArraySize=str(count), BitSize=str(bits),
                      BitAddress=str(offset), ArraySkip=str(skip), DefaultValue=value)
        parameters[name] = ParameterSpec(name, kind, "synthetic.xml", fields)
    return UnitSpec(unit_type + ".xml", {"Type": unit_type}, ("synthetic.xml",), parameters)


class Reply:
    def __init__(self, document): self.lines = ("347-" + document, "344 End XML")


class Session:
    def __init__(self, spec):
        self.spec, self.unit_type = spec, spec.unit_type
        self.current = spec.defaults()
        self.calls = []
        self.failure = None
        self.rollback_failure = False
        self.source = None

    def values(self): return dict(self.current)

    def info(self, _name):
        root = ET.Element("Parameters")
        for p in self.spec.parameters.values():
            node = ET.SubElement(root, "Param")
            for k, v in p.fields.items(): ET.SubElement(node, k).text = v
        return Reply(ET.tostring(root, encoding="unicode"))

    def set(self, name, value):
        self.calls.append((name, value))
        if self.rollback_failure and len(self.calls) > 2: raise RuntimeError("rollback connection lost")
        self.current[name] = value
        if name == self.failure:
            self.failure = None
            raise RuntimeError("write outcome initially uncertain")


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.source, self.target = fixture("KEY4"), fixture("KEY1")
        self.convert = OfflineConversion(self.source, self.target)
        self.a, self.b = Session(self.source), Session(self.target)
        self.a.current.update(UnitName="SOURCE", JPCommand="13 11 12 15", SRCommand="0 7 0 0",
                              GroupAddress="10 20 30 40 50 60 70 80", TimerHighByte="1 2 3 4",
                              UnitAddress="10", Project="SOURCE", NetworkAddress="33", LearnedFlag="1")
        self.b.current.update(UnitAddress="99", Project="TARGET", NetworkAddress="44", LearnedFlag="0")

    def test_configuration_copies_all_stored_slots_and_preserves_target_identity(self):
        p = self.convert.plan(self.a.values(), self.b.values())
        self.assertEqual(p.changes["JPCommand"], (13, 11, 12, 15))
        self.assertEqual(p.changes["GroupAddress"], (10, 20, 30, 40, 50, 60, 70, 80))
        self.assertEqual(p.as_dict()["stored_key_slots"], 4)
        self.assertEqual(p.as_dict()["inactive_source_keys"], [2, 3, 4])
        result = self.convert.apply(self.b, p)
        self.assertTrue(result["verified"])
        self.assertFalse(result["saved"])
        for field, value in (("UnitAddress", "99"), ("Project", "TARGET"), ("NetworkAddress", "44"), ("LearnedFlag", "0")):
            self.assertEqual(self.b.current[field], value)
            self.assertIn(field, result["retained_target"])

    def test_independent_fixed_raw_vector_preserves_reserved_bits(self):
        p = self.convert.plan(self.a.values(), self.b.values())
        image = MemoryImage.from_bytes(bytes([0xA5]) * 256)
        raw = self.convert.codec.encode_many(p.changes).apply(image)
        self.assertEqual(raw.read(50, 8), bytes.fromhex("d0a5b7a5c0a5f0a5"))
        self.assertEqual(raw.read(80, 8), bytes([10, 20, 30, 40, 50, 60, 70, 80]))
        self.assertEqual(raw.read(31, 4), bytes([0xA5]) * 4)

    def test_every_pair_supported_and_source_snapshot_not_mutated(self):
        for a in ("KEY1", "KEY2", "KEY4"):
            for b in ("KEY1", "KEY2", "KEY4"):
                with self.subTest(a=a, b=b):
                    x, y = Session(fixture(a)), Session(fixture(b))
                    x.current["GroupAddress"] = "1 2 3 4 5 6 7 8"
                    saved = x.values()
                    self.assertTrue(OfflineConversion(x.spec, y.spec).configure(x, y)["verified"])
                    self.assertEqual(x.values(), saved)

    def test_missing_array_and_invalid_width_rejected(self):
        for field, value in (("JPCommand", "13 11"), ("DebounceTime", "64")):
            source = self.a.values(); source[field] = value
            with self.assertRaises(ConversionError): self.convert.plan(source, self.b.values())
        target = self.b.values(); del target["CUSTYPE"]
        with self.assertRaises(ConversionError): self.convert.plan(self.a.values(), target)

    def test_application_translation_and_other_families_rejected(self):
        for value in ("56 57", "202 255"):
            self.a.current["Application"] = value
            with self.assertRaises(ConversionError): self.convert.plan(self.a.values(), self.b.values())
        with self.assertRaises(ConversionError): OfflineConversion(fixture("KEYE1"), self.target)
        with self.assertRaises(ConversionError): OfflineConversion(replace(self.source, filename="KEY4_old.xml"), self.target)

    def test_changed_schema_rejected(self):
        fields = dict(self.target.parameters["JPCommand"].fields); fields["BitSize"] = "8"
        params = dict(self.target.parameters); params["JPCommand"] = replace(params["JPCommand"], fields=fields)
        with self.assertRaises(ConversionError): OfflineConversion(self.source, replace(self.target, parameters=params))

    def test_stale_plan_and_forged_factory_write_rejected_before_sets(self):
        p = self.convert.plan(self.a.values(), self.b.values())
        bad = replace(p, changes={**p.changes, "PatchEnable": (1, 2)})
        with self.assertRaises(ConversionError): self.convert.apply(self.b, bad)
        self.b.current["Project"] = "CHANGED"
        with self.assertRaises(ConversionError): self.convert.apply(self.b, p)
        self.assertFalse(self.b.calls)

    def test_wrong_session_identity_rejected(self):
        p = self.convert.plan(self.a.values(), self.b.values())
        self.b.unit_type = "KEY2"
        with self.assertRaises(ConversionError): self.convert.apply(self.b, p)
        self.assertFalse(self.b.calls)

    def test_physical_source_session_rejected(self):
        p = self.convert.plan(self.a.values(), self.b.values())
        self.b.source = "//PHYSICAL/254/p/1"
        with self.assertRaises(ConversionError): self.convert.apply(self.b, p)
        self.assertFalse(self.b.calls)

    def test_partial_failed_write_is_rolled_back_and_reported(self):
        p = self.convert.plan(self.a.values(), self.b.values())
        self.b.failure = "GroupAddress"
        with self.assertRaises(ConversionApplyError) as ctx: self.convert.apply(self.b, p)
        self.assertFalse(ctx.exception.rollback_errors)
        self.assertEqual(self.convert._snapshot(self.target, self.b.values(), self.target.parameters), dict(p.expected))

    def test_rollback_failure_reported(self):
        p = self.convert.plan(self.a.values(), self.b.values())
        self.b.failure = "GroupAddress"; self.b.rollback_failure = True
        with self.assertRaises(ConversionApplyError) as ctx: self.convert.apply(self.b, p)
        self.assertTrue(ctx.exception.rollback_errors)

    def test_plan_is_immutable_and_unknown_source_is_reported(self):
        self.a.current["UnmappedUIField"] = "opaque"
        p = self.convert.plan(self.a.values(), self.b.values())
        self.assertIn("UnmappedUIField", p.ignored_source)
        with self.assertRaises(TypeError): p.changes["UnitName"] = "BAD"


@unittest.skipUnless(os.environ.get("CBUS_TOOLKIT_EXE"), "Set CBUS_TOOLKIT_EXE for exact frontend evidence")
class BinaryEvidenceTests(unittest.TestCase):
    def test_original_attribute_registration_and_alignment_exclusion(self):
        data = Path(os.environ["CBUS_TOOLKIT_EXE"]).read_bytes()
        u16 = lambda n: struct.unpack_from("<H", data, n)[0]
        u32 = lambda n: struct.unpack_from("<I", data, n)[0]
        pe = u32(60); optional = pe + 24; sections = optional + u16(pe + 20); base = u32(optional + 28)
        def at(address, length):
            rva = address - base
            for i in range(u16(pe + 6)):
                s = sections + i * 40; begin = u32(s + 12)
                if begin <= rva < begin + max(u32(s + 8), u32(s + 16)):
                    offset = u32(s + 20) + rva - begin
                    return data[offset:offset + length]
            self.fail("Address outside PE sections")
        registrations = {0xCB529D: "Application", 0xCB539C: "UnitName", 0xCC5AAF: "LearnAnyApp", 0xCC5AD5: "LearnMode",
                         0xCC6479: "AreaGroupAddress", 0xCC64D9: "StatusReportInterval", 0xCC6D27: "GroupAddress",
                         0xCC6D4D: "DebounceTime", 0xCC6D89: "IndicatorBrightness", 0xCC6DAF: "LongPressTime",
                         0xCC6DDD: "RampRate", 0xCC6E29: "JPCommand", 0xCC6E4F: "SRCommand", 0xCC6E75: "LPCommand",
                         0xCC6E9B: "LRCommand", 0xCC6EC1: "BlockAllocation", 0xCC6EE7: "IndicatorBlockAssignment",
                         0xCC6F0D: "IndicatorFunction", 0xCC7185: "TimerHighByte", 0xCC71DD: "TimerLowByte",
                         0xCC7235: "TimerExpiryCommand", 0xCC7297: "EEPROMLevelStore", 0xCC72BD: "LightIndex",
                         0xCC72E3: "LightLevel", 0xCC7309: "LightLevelStore1", 0xCC732F: "LightLevelStore2"}
        self.assertEqual(set(registrations.values()), set(COPY_PARAMETERS))
        for address, name in registrations.items():
            instruction = at(address, 5)
            self.assertEqual(instruction[0], 0x68)
            self.assertEqual(at(struct.unpack_from("<I", instruction, 1)[0], len(name) * 2).decode("utf-16le"), name)
        self.assertEqual(at(0xCC05B3, 5), bytes.fromhex("bac008cc00"))
        self.assertEqual(at(0xCC08C0, 6).decode("utf-16le"), "OID")
        # LearnAnyApp/Mode are conditionally mutable; LearnedFlag has a distinct
        # current-vs-original-state branch and is deliberately outside the API.
        self.assertEqual(at(0xCC5FE9, 2), bytes.fromhex("3c01"))


@unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST") and os.environ.get("CBUS_UNITSPEC_DIR"), "Set native server and unit specs for conversion acceptance")
class NativeConversionTests(unittest.TestCase):
    def test_nine_classic_pairs_native_values_raw_bytes_and_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        store = UnitSpecStore(os.environ["CBUS_UNITSPEC_DIR"])
        project = "V" + uuid4().hex[:7].upper()
        with CGateClient(os.environ["CBUS_CGATE_TEST_HOST"], port=int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023")), timeout=20) as client:
            client.command("PROJECT NEW " + project)
            try:
                db = NativeDatabase(client)
                db.create_network(project, 254, "Conversion_Offline", "Cni", "127.0.0.1:29999")
                client.command("PROJECT SAVE " + project)
                programmer = Programmer(client); network = f"//{project}/254"
                units = (("KEY1", "5031N"), ("KEY2", "5032N"), ("KEY4", "5034N"))
                for i, (unit, catalog) in enumerate(units):
                    db.create_unit(network, 220 + i, "Destination" + str(i), unit, "1.2.67", catalog_number=catalog)
                for source_index, (source_type, source_catalog) in enumerate(units):
                    with programmer.new(network, source_type, "1.2.67", catalog_number=source_catalog) as source:
                        source.set("UnitName", "COPIED" + str(source_index))
                        source.set("GroupAddress", f"{11 + source_index} 22 33 44 55 66 77 88")
                        source.set("JPCommand", "13 11 12 15"); source.set("SRCommand", "0 7 1 2")
                        source.set("LPCommand", "4 5 2 0"); source.set("LRCommand", "14 14 14 15")
                        source.set("TimerHighByte", "1 2 3 4"); source.set("TimerLowByte", "10 20 30 40")
                        for field, value in {
                            "Application": "57 255", "LearnAnyApp": "1", "LearnMode": "1",
                            "AreaGroupAddress": "37", "StatusReportInterval": "4", "DebounceTime": "5",
                            "IndicatorBrightness": "123", "LongPressTime": "12", "RampRate": "2 4",
                            "BlockAllocation": "8 4 2 1", "IndicatorBlockAssignment": "3 2 1 0",
                            "IndicatorFunction": "1 2 3 0", "TimerExpiryCommand": "15 12 6 0",
                            "EEPROMLevelStore": "1", "LightIndex": "2",
                            "LightLevel": " ".join(map(str, range(16))),
                            "LightLevelStore1": "10 20 30 40", "LightLevelStore2": "40 30 20 10",
                        }.items(): source.set(field, value)
                        source_values = source.values()
                        vector = source.get_raw_data(50, 8).lines[-1].split("RawData=", 1)[1]
                        self.assertEqual(vector, "d04eb75ec12ef20f")
                    for target_index, (target_type, _) in enumerate(units):
                        path = network + "/p/" + str(220 + target_index)
                        with self.subTest(source=source_type, target=target_type):
                            converter = OfflineConversion(store.load(source_type + ".xml"), store.load(target_type + ".xml"))
                            with programmer.load(network, "/db" + path) as target:
                                before = target.values()
                                plan = converter.plan(source_values, before)
                                self.assertTrue(converter.apply(target, plan)["verified"])
                                self.assertEqual(target.get_raw_data(50, 8).lines[-1].split("RawData=", 1)[1], vector)
                                self.assertEqual(target.values()["UnitAddress"], before["UnitAddress"])
                                target.save_to_source()
                            with programmer.load(network, "/db" + path) as reloaded:
                                values = reloaded.values()
                                self.assertEqual(values["UnitName"].strip(), "COPIED" + str(source_index))
                                for field in COPY_PARAMETERS:
                                    self.assertEqual(values[field], source_values[field], field)
                                self.assertEqual(values["UnitAddress"], before["UnitAddress"])
                                self.assertEqual(reloaded.get_raw_data(50, 8).lines[-1].split("RawData=", 1)[1], vector)
            finally:
                client.command("PROJECT CLOSE " + project)
                client.command("PROJECT DELETE " + project)


if __name__ == "__main__": unittest.main()
