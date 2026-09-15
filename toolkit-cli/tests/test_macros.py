"""Classic macro vectors, transaction checks and opt-in native acceptance."""
from dataclasses import replace
from html.parser import HTMLParser
import os
from pathlib import Path
import struct
import unittest
from uuid import uuid4
import xml.etree.ElementTree as ET

from cbus_toolkit.macros import ClassicKeys, KeyPlan, MacroApplyError, MacroError, MICRO_FUNCTIONS, PRESETS, STAGES
from cbus_toolkit.memory import MemoryImage
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec, UnitSpecStore


# Independent vectors transcribed from the help's event tables and the original
# binary's classic micro-function registration arguments (see docs/macros.md).
VECTORS = {"on": (13, 0, 0, 0), "off": (15, 0, 0, 0), "toggle": (11, 0, 0, 0),
           "dimmer": (0, 11, 2, 14), "dimmer_memory": (0, 3, 2, 14),
           "dimmer_up": (0, 13, 5, 14), "dimmer_down": (0, 15, 4, 14),
           "on_up": (0, 3, 5, 14), "off_down": (0, 3, 4, 14),
           "timer": (11, 7, 0, 7), "bellpress": (13, 15, 13, 15),
           "soft_up": (14, 10, 5, 14), "soft_down": (14, 9, 4, 14),
           "preset1": (0, 12, 9, 0), "preset2": (0, 6, 9, 0),
           "trigger1": (12, 0, 0, 0), "trigger2": (6, 0, 0, 0), "unused": (0, 0, 0, 0)}


def fixture(unit_type="KEY4"):
    parameters = {}
    rows = (("JPCommand", 0x32, 4, 4, 4, 1, [11] * 4),
            ("SRCommand", 0x32, 4, 4, 0, 1, [0] * 4),
            ("LPCommand", 0x33, 4, 4, 4, 1, [0] * 4),
            ("LRCommand", 0x33, 4, 4, 0, 1, [0] * 4),
            ("BlockAllocation", 0x3A, 4, 8, 0, 0, [1, 2, 4, 8]),
            ("GroupAddress", 0x50, 8, 8, 0, 0, [255] * 8),
            ("Application", 0x21, 2, 8, 0, 0, [56, 255]),
            ("TimerHighByte", 0x44, 4, 8, 0, 0, [0] * 4),
            ("TimerLowByte", 0x48, 4, 8, 0, 0, [0] * 4),
            ("TimerExpiryCommand", 0x4C, 4, 4, 0, 0, [15] * 4),
            ("LightLevelStore1", 0x11, 4, 8, 0, 0, [255] * 4),
            ("LightLevelStore2", 0x15, 4, 8, 0, 0, [255] * 4))
    for name, address, count, bits, offset, skip, default in rows:
        fields = {"Name": name, "Type": "int", "Address": str(address), "ArraySize": str(count),
                  "BitSize": str(bits), "BitAddress": str(offset), "ArraySkip": str(skip),
                  "DefaultValue": " ".join(str(value) for value in default)}
        parameters[name] = ParameterSpec(name, "int", "fixture.xml", fields)
    return UnitSpec(unit_type + ".xml", {"Type": unit_type}, ("fixture.xml",), parameters)


class Reply:
    def __init__(self, text):
        self.lines = ("347-" + text, "344 End XML")


class Session:
    def __init__(self, spec):
        self.unit_type = spec.unit_type
        self.spec = spec
        self.current = spec.defaults()
        self.calls = []
        self.failure = None
        self.fail_rollback = False

    def values(self):
        return dict(self.current)

    def info(self, name):
        root = ET.Element("Parameters")
        for parameter in self.spec.parameters.values():
            node = ET.SubElement(root, "Param")
            for key, value in parameter.fields.items():
                ET.SubElement(node, key).text = value
        return Reply(ET.tostring(root, encoding="unicode"))

    def set(self, name, value):
        self.calls.append((name, value))
        if self.failure == name:
            self.failure = None
            self.current[name] = value  # A failed command can have partially run.
            raise RuntimeError("simulated failed write")
        if self.fail_rollback and len(self.calls) > 2:
            raise RuntimeError("simulated failed rollback")
        self.current[name] = value


class MacroTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.keys = ClassicKeys(self.spec)
        self.session = Session(self.spec)

    def test_all_source_vectors_and_exact_native_nibbles(self):
        self.assertEqual(set(PRESETS), set(VECTORS))
        for preset, vector in VECTORS.items():
            with self.subTest(preset=preset):
                options = {"timer_seconds": 300} if preset == "timer" else {}
                plan = self.keys.plan(self.spec.defaults(), key=2, preset=preset, **options)
                updated = dict(plan.expected); updated.update(plan.changes)
                self.assertEqual(tuple(updated[name][1] for name in STAGES), vector)
                before = MemoryImage.from_bytes(b"\xa5" * 128)
                data = self.keys.codec.encode_many(plan.changes).apply(before)
                expected_first = vector[0] << 4 | vector[1]
                expected_second = vector[2] << 4 | vector[3]
                # Unchanged fields need original default bytes to compare full
                # stage bytes; set all four fields for this isolated vector.
                data = self.keys.codec.encode_many({name: updated[name] for name in STAGES}).apply(before)
                self.assertEqual(data.read(0x34, 2), bytes([expected_first, expected_second]))
                self.assertEqual(tuple(updated[name][0] for name in STAGES), (11, 0, 0, 0))

    def test_timer_group_and_recall_split_are_grounded_and_local(self):
        plan = self.keys.plan(self.spec.defaults(), key=3, preset="timer", group=17,
                              timer_seconds=300, recall1=64, recall2=128)
        self.assertEqual(plan.block, 3)
        self.assertEqual(plan.changes["GroupAddress"], (255, 255, 17, 255, 255, 255, 255, 255))
        self.assertEqual(plan.changes["TimerHighByte"], (0, 0, 1, 0))
        self.assertEqual(plan.changes["TimerLowByte"], (0, 0, 44, 0))
        self.assertEqual(plan.changes["LightLevelStore1"], (255, 255, 64, 255))
        max_timer = self.keys.plan(self.spec.defaults(), key=1, preset="timer", timer_seconds=65535)
        self.assertEqual(max_timer.changes["TimerHighByte"][0], 255)
        self.assertEqual(max_timer.changes["TimerLowByte"][0], 255)
        self.assertFalse(plan.as_dict()["saved"])

    def test_presets_preserve_unrequested_block_indicator_and_timer_settings(self):
        plan = self.keys.plan(self.spec.defaults(), key=1, preset="dimmer")
        self.assertEqual(set(plan.changes), set(STAGES))
        self.assertIsNone(plan.block)
        for name, values in plan.expected.items():
            if name not in STAGES:
                self.assertEqual(values, tuple(int(x) for x in self.spec.defaults()[name].split()))

    def test_unsupported_types_and_changed_schema_rejected(self):
        for unit_type in ("KEYE1", "KEYGL5", "KEYB6A", "SENPIR"):
            with self.assertRaises(MacroError):
                ClassicKeys(fixture(unit_type))
        fields = dict(self.spec.get("JPCommand").fields, BitSize="8")
        spec = replace(self.spec, parameters=dict(self.spec.parameters, JPCommand=replace(self.spec.get("JPCommand"), fields=fields)))
        with self.assertRaises(MacroError):
            ClassicKeys(spec)

    def test_physical_key_counts_and_value_validation(self):
        for unit_type, count in (("KEY1", 1), ("KEY2", 2), ("KEY4", 4)):
            keys = ClassicKeys(fixture(unit_type))
            with self.assertRaises(MacroError):
                keys.plan(keys.spec.defaults(), key=count + 1, preset="on")
        for options in ({"key": 0}, {"key": True}, {"preset": "doublepress"}, {"group": 255},
                        {"group": -1}, {"block": 5}, {"timer_seconds": 65536},
                        {"timer_seconds": 1.5}, {"timer_seconds": 30, "expiry": "toggle"},
                        {"recall1": 256}):
            with self.subTest(options=options), self.assertRaises(MacroError):
                self.keys.plan(self.spec.defaults(), **dict({"key": 1, "preset": "on"}, **options))
        values = self.spec.defaults(); values["Application"] = "202 255"
        with self.assertRaises(MacroError):
            self.keys.plan(values, key=1, preset="on", group=7)

    def test_disabled_timer_requires_explicit_value(self):
        with self.assertRaisesRegex(MacroError, "disabled"):
            self.keys.plan(self.spec.defaults(), key=1, preset="timer")
        self.keys.plan(self.spec.defaults(), key=1, preset="timer", timer_seconds=0)

    def test_shared_blocks_require_explicit_intent(self):
        current = self.spec.defaults(); current["BlockAllocation"] = "1 1 4 8"
        with self.assertRaisesRegex(MacroError, "also assigned"):
            self.keys.plan(current, key=1, preset="on", group=9)
        plan = self.keys.plan(current, key=1, preset="on", group=9, allow_shared_block=True)
        self.assertEqual(plan.shared_keys, (2,))
        separate = self.keys.plan(current, key=1, preset="on", group=9, block=2)
        self.assertEqual(separate.changes["BlockAllocation"], (2, 1, 4, 8))
        current["BlockAllocation"] = "3 2 4 8"
        with self.assertRaises(MacroError):
            self.keys.plan(current, key=1, preset="on", group=9)

    def test_apply_preconditions_and_full_array_readback(self):
        plan = self.keys.plan(self.session.values(), key=2, preset="bellpress", group=7)
        result = self.keys.apply(self.session, plan)
        self.assertTrue(result["verified"])
        self.assertFalse(result["saved"])
        self.assertEqual(self.session.current["JPCommand"], "11 13 11 11")
        self.assertTrue(all(len(value.split()) in (4, 8) for _, value in self.session.calls))
        with self.assertRaisesRegex(MacroError, "changed since"):
            self.keys.apply(self.session, plan)

    def test_apply_refuses_wrong_native_type_and_schema_before_writes(self):
        plan = self.keys.plan(self.session.values(), key=1, preset="on")
        self.session.unit_type = "KEY1"
        with self.assertRaises(MacroError):
            self.keys.apply(self.session, plan)
        self.session.unit_type = "KEY4"
        old = self.session.spec.get("JPCommand")
        self.session.spec = replace(self.spec, parameters=dict(self.spec.parameters, JPCommand=replace(old, fields=dict(old.fields, Address="100"))))
        with self.assertRaises(MacroError):
            self.keys.apply(self.session, plan)
        self.assertEqual(self.session.calls, [])

    def test_failed_apply_rolls_back_even_partially_failed_parameter(self):
        original = self.keys._snapshot(self.session.values())
        self.session.failure = "LPCommand"
        plan = self.keys.plan(self.session.values(), key=1, preset="dimmer")
        with self.assertRaises(MacroApplyError) as error:
            self.keys.apply(self.session, plan)
        self.assertFalse(error.exception.rollback_errors)
        self.assertEqual(self.keys._snapshot(self.session.values()), original)

    def test_rollback_failure_is_not_hidden(self):
        self.session.failure = "LPCommand"
        self.session.fail_rollback = True
        plan = self.keys.plan(self.session.values(), key=1, preset="dimmer")
        with self.assertRaises(MacroApplyError) as error:
            self.keys.apply(self.session, plan)
        self.assertTrue(error.exception.rollback_errors)

    def test_unknown_plan_fields_and_missing_snapshot_are_rejected(self):
        plan = self.keys.plan(self.session.values(), key=1, preset="on")
        forged = replace(plan, changes={"Unknown": (1,)})
        with self.assertRaises(MacroError):
            self.keys.apply(self.session, forged)
        with self.assertRaises(MacroError):
            self.keys.plan({}, key=1, preset="on")
        self.assertEqual(self.session.calls, [])


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows = []; self.row = None; self.cell = None
    def handle_starttag(self, tag, attrs):
        if tag == "tr": self.row = []
        if tag in ("td", "th"): self.cell = []
    def handle_data(self, text):
        if self.cell is not None: self.cell.append(text)
    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            if self.row is not None: self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        if tag == "tr" and self.row is not None:
            self.rows.append(self.row); self.row = None


@unittest.skipUnless(os.environ.get("CBUS_TOOLKIT_HELP_DIR"), "Set CBUS_TOOLKIT_HELP_DIR for original help event-table verification")
class VendorHelpTests(unittest.TestCase):
    def test_all_presets_against_original_help_event_tables(self):
        labels = {"idle": "idle", "on": "on key", "off": "off key", "toggle": "toggle",
                  "downcycle": "downcycle", "memory_toggle2": "memory toggle 2", "up": "up key", "down": "down key",
                  "end_ramp": "end ramp", "retrigger_timer": "retrigger timer", "ramp_recall1": "ramp recall 1",
                  "ramp_off": "ramp off", "recall1": "recall 1", "recall2": "recall 2"}
        for name, preset in PRESETS.items():
            parser = TableParser()
            parser.feed((Path(os.environ["CBUS_TOOLKIT_HELP_DIR"]) / preset.help_topic).read_text(encoding="cp1252"))
            row = [labels[event] for event in preset.events]
            candidates = [[cell.lower() for cell in r] for r in parser.rows]
            if name in ("dimmer", "dimmer_memory"):
                row.insert(0, "memory" if name == "dimmer_memory" else "toggle")
            with self.subTest(preset=name):
                self.assertIn(row, candidates)


@unittest.skipUnless(os.environ.get("CBUS_TOOLKIT_EXE"), "Set CBUS_TOOLKIT_EXE for original binary micro-code verification")
class VendorBinaryTests(unittest.TestCase):
    def test_registration_codes_and_timer_helpers_in_original_exe(self):
        image = Path(os.environ["CBUS_TOOLKIT_EXE"]).read_bytes()
        u16 = lambda o: struct.unpack_from("<H", image, o)[0]
        u32 = lambda o: struct.unpack_from("<I", image, o)[0]
        pe = u32(60); optional = pe + 24; sections = optional + u16(pe + 20); base = u32(optional + 28)
        def at(va, length):
            rva = va - base
            for i in range(u16(pe + 6)):
                offset = sections + i * 40; start = u32(offset + 12)
                if start <= rva < start + max(u32(offset + 8), u32(offset + 16)):
                    raw = u32(offset + 20) + rva - start
                    return image[raw:raw + length]
            raise AssertionError("VA is outside PE sections")
        # Each sequence pushes FunctionType, new-device encoding, family; EDX
        # later carries the classic code. RegisterKeyMicroFunction sets it via
        # TKeyMicroFunction.SetCBusValue. Names resolve from inline UTF16 strings
        # or documented resource IDs in docs/macros.md.
        registrations = {"on": (0xC8DD13, "6a0d6a476a02"), "off": (0xC8DD2D, "6a0f6a406a02"),
                         "toggle": (0xC8DCD4, "6a0b6a4f6a02"), "downcycle": (0xC8DBA8, "6a026a196a01"),
                         "memory_toggle2": (0xC8DCEE, "6a036a4e6a02"), "end_ramp": (0xC8DD47, "6a0e6a0e6a01"),
                         "retrigger_timer": (0xC8DD61, "6a0768970000006a03"), "recall1": (0xC8DC1B, "6a0c6a426a02"),
                         "recall2": (0xC8DBF6, "6a066a466a02"), "ramp_recall1": (0xC8DCAF, "6a0a6a566a02"),
                         "ramp_off": (0xC8DC8A, "6a096a506a02"), "up": (0xC8DBDC, "6a056a176a01"),
                         "down": (0xC8DBC2, "6a046a116a01")}
        for name, (address, raw) in registrations.items():
            data = bytes.fromhex(raw)
            with self.subTest(name=name):
                self.assertEqual(at(address, len(data)), data)
                self.assertEqual(data[1], MICRO_FUNCTIONS[name])
        self.assertEqual(at(0x7F0E58, 3), bytes.fromhex("8a45fe"))  # LowByte of AX
        self.assertEqual(at(0x7F0E6C, 3), bytes.fromhex("8a45ff"))  # HighByte of AX


@unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST") and os.environ.get("CBUS_UNITSPEC_DIR"), "Set native server and unit specs for macro acceptance")
class NativeMacroTests(unittest.TestCase):
    def test_every_preset_native_values_bytes_and_database_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.programming import Programmer
        store = UnitSpecStore(os.environ["CBUS_UNITSPEC_DIR"])
        keys = ClassicKeys(store.load("KEY4.xml"))
        project = "K" + uuid4().hex[:7].upper()
        with CGateClient(os.environ["CBUS_CGATE_TEST_HOST"], port=int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023")), timeout=20) as client:
            client.command("PROJECT NEW " + project)
            try:
                client.command("PROJECT USE " + project)
                client.command("DBCREATENET 254 Macro_Offline Cni 127.0.0.1:29999")
                client.command("NET LOAD DB " + project)
                client.command("PROJECT SAVE " + project)
                path = f"//{project}/254/p/220"
                client.command(f"DBADDSAFE //{project}/254 Unit 220 Macro_Test")
                for name, value in (("UnitType", "KEY4"), ("FirmwareVersion", "1.2.67"), ("CatalogNumber", "5034N"), ("UnitName", "KEY4")):
                    client.command(f"DBSET {path}/{name} {value}")
                programmer = Programmer(client)
                with programmer.new(f"//{project}/254", "KEY4", "1.2.67", catalog_number="5034N", name="MACRO_" + uuid4().hex[:8]) as session:
                    for preset, vector in VECTORS.items():
                        with self.subTest(preset=preset):
                            options = {"timer_seconds": 300} if preset == "timer" else {}
                            result = keys.configure(session, key=2, preset=preset, group=17, **options)
                            self.assertTrue(result["verified"])
                            actual = session.values()
                            self.assertEqual(tuple(int(actual[name].split()[1], 0) for name in STAGES), vector)
                            raw = session.get_raw_data(0x34, 2).lines[-1].split("RawData=", 1)[1]
                            self.assertEqual(raw, bytes([vector[0] << 4 | vector[1], vector[2] << 4 | vector[3]]).hex())
                    result = keys.configure(session, key=2, preset="timer", group=17, timer_seconds=300)
                    session.save("/db" + path)
                # Loading a fresh database session also verifies type discovery.
                with programmer.load(f"//{project}/254", "/db" + path, name="MACRO_" + uuid4().hex[:8]) as session:
                    values = session.values()
                    self.assertEqual(values["TimerHighByte"], "0x0 0x1 0x0 0x0")
                    self.assertEqual(values["TimerLowByte"], "0x0 0x2c 0x0 0x0")
                    self.assertTrue(keys.configure(session, key=1, preset="on", group=22)["verified"])
                for unit_type, catalog, last_key in (("KEY1", "5031N", 1), ("KEY2", "5032N", 2)):
                    supported = ClassicKeys(store.load(unit_type + ".xml"))
                    with programmer.new(f"//{project}/254", unit_type, "1.2.67", catalog_number=catalog,
                                        name="MACRO_" + uuid4().hex[:8]) as session:
                        self.assertTrue(supported.configure(session, key=last_key, preset="bellpress", group=31)["verified"])
            finally:
                client.command("PROJECT CLOSE " + project)
                client.command("PROJECT DELETE " + project)


if __name__ == "__main__":
    unittest.main()
