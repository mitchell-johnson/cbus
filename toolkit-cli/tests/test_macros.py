"""Classic macro vectors, transaction checks and opt-in native acceptance."""
from contextlib import contextmanager
from dataclasses import replace
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import socket
import struct
import unittest
from uuid import uuid4
import xml.etree.ElementTree as ET

from cbus_toolkit.macros import (ClassicKeys, EXCLUDED_PRESETS, GUARDED_PARAMETERS, HELP_TABLE_EVENTS, KeyPlan,
                                 MacroApplyError, MacroError, MICRO_FUNCTIONS, PRESETS, STAGES, SUPPORTED_UNITS,
                                 TRIGGER_PRESETS, _READ_FIELDS, _numbers)
from cbus_toolkit.memory import MemoryImage
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec, UnitSpecStore


# Independent vectors transcribed from the original binary's micro-function
# group registrations (see docs/macros.md). Bell Press and Soft Up/Down differ
# from their help event tables; HELP_VECTORS keeps the help rows.
VECTORS = {"on": (13, 0, 0, 0), "off": (15, 0, 0, 0), "toggle": (11, 0, 0, 0),
           "dimmer": (0, 11, 2, 14), "dimmer_memory": (0, 3, 2, 14),
           "dimmer_up": (0, 13, 5, 14), "dimmer_down": (0, 15, 4, 14),
           "on_up": (0, 3, 5, 14), "off_down": (0, 3, 4, 14),
           "timer": (11, 7, 0, 7), "bellpress": (13, 15, 0, 15),
           "soft_up": (0, 10, 5, 14), "soft_down": (0, 9, 4, 14),
           "preset1": (0, 12, 9, 0), "preset2": (0, 6, 9, 0),
           "trigger1": (12, 0, 0, 0), "trigger2": (6, 0, 0, 0), "unused": (0, 0, 0, 0)}
HELP_VECTORS = {"bellpress": (13, 15, 13, 15), "soft_up": (14, 10, 5, 14), "soft_down": (14, 9, 4, 14)}


def options_for(preset):
    return {"timer_seconds": 300} if preset == "timer" else {}


def trigger_ready(test, keys, session, preset, key, **options):
    """Prove a trigger preset is refused off application 202, then select 202."""
    if preset not in TRIGGER_PRESETS:
        return None
    before = session.values()
    with test.assertRaisesRegex(MacroError, "Trigger Control"):
        keys.configure(session, key=key, preset=preset, **options)
    test.assertEqual(session.values(), before)
    session.set("Application", "202 " + " ".join(before["Application"].split()[1:]))
    return before["Application"]


def fixture(unit_type="KEY4", extra=()):
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
            ("LightLevelStore2", 0x15, 4, 8, 0, 0, [255] * 4)) + tuple(extra)
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
                current = self.spec.defaults()
                if preset in TRIGGER_PRESETS:
                    current["Application"] = "202 255"
                plan = self.keys.plan(current, key=2, preset=preset, **options_for(preset))
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

    def test_trigger_presets_require_trigger_control_application(self):
        for preset in sorted(TRIGGER_PRESETS):
            with self.subTest(preset=preset):
                with self.assertRaisesRegex(MacroError, r"Trigger Control \(202\)"):
                    self.keys.plan(self.spec.defaults(), key=1, preset=preset)
                current = self.spec.defaults()
                current["Application"] = "202 255"
                plan = self.keys.plan(current, key=1, preset=preset, group=9)
                self.assertEqual(plan.changes["GroupAddress"][0], 9)
        # Other presets remain available on Trigger Control; group edits there
        # still require a Lighting Type application.
        current = self.spec.defaults()
        current["Application"] = "202 255"
        self.assertEqual(self.keys.plan(current, key=1, preset="on").changes["JPCommand"][0], 13)
        with self.assertRaisesRegex(MacroError, "Lighting Type"):
            self.keys.plan(current, key=1, preset="on", group=9)

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


class ClassicFamilyTests(unittest.TestCase):
    def test_family_key_counts_and_refusals(self):
        for unit_type, count in SUPPORTED_UNITS.items():
            with self.subTest(unit_type=unit_type):
                keys = ClassicKeys(fixture(unit_type))
                keys.plan(keys.spec.defaults(), key=count, preset="on")
                with self.assertRaises(MacroError):
                    keys.plan(keys.spec.defaults(), key=count + 1, preset="on")
        for unit_type in ("BCNC4A", "BCNC4B", "KEYV1SP", "KEYCIR1"):
            with self.subTest(unit_type=unit_type), self.assertRaises(MacroError):
                ClassicKeys(fixture(unit_type))
        with self.assertRaisesRegex(MacroError, "forces fixed micro-function defaults"):
            ClassicKeys(fixture("BCNC4A"))

    def test_guarded_parameters_are_never_planned_or_written(self):
        for unit_type, guarded in GUARDED_PARAMETERS.items():
            extra = [(name, 0x6F, 1, 8, 0, 0, [0xA5]) for name in guarded]
            spec = fixture(unit_type, extra)
            keys = ClassicKeys(spec)
            session = Session(spec)
            with self.subTest(unit_type=unit_type):
                plan = keys.plan(session.values(), key=keys.key_count, preset="timer", group=17,
                                 timer_seconds=300, recall1=64, recall2=128)
                self.assertFalse(set(plan.changes) & set(guarded))
                keys.apply(session, plan)
                self.assertFalse({name for name, _ in session.calls} & set(guarded))
                self.assertEqual({name: session.current[name] for name in guarded}, {name: "165" for name in guarded})
                forged = replace(plan, changes={**plan.changes, guarded[0]: (0,)})
                with self.assertRaisesRegex(MacroError, "outside the classic key workflow"):
                    keys.apply(session, forged)

    def test_aux_types_refuse_bell_press_but_accept_other_presets(self):
        for unit_type in ("KEYAUX4", "DINAUX4"):
            keys = ClassicKeys(fixture(unit_type))
            session = Session(keys.spec)
            with self.subTest(unit_type=unit_type):
                self.assertEqual(EXCLUDED_PRESETS[unit_type], {"bellpress"})
                with self.assertRaisesRegex(MacroError, "AUX subset"):
                    keys.plan(session.values(), key=1, preset="bellpress")
                allowed = keys.plan(session.values(), key=1, preset="toggle")
                with self.assertRaisesRegex(MacroError, "AUX subset"):
                    keys.apply(session, replace(allowed, preset="bellpress"))
                self.assertEqual(session.calls, [])
                self.assertTrue(keys.apply(session, allowed)["verified"])


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
            # Three help tables differ from Toolkit's assigned group; they are
            # retained separately and compared here against their help rows.
            row = [labels[event] for event in HELP_TABLE_EVENTS.get(name, preset.events)]
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


NATIVE = bool(os.environ.get("CBUS_UNITSPEC_DIR") and (
    os.environ.get("CBUS_CGATE_TEST_HOST") or
    (os.environ.get("CBUS_NATIVE_SERVICE_BACKEND") == "local" and os.environ.get("CBUS_CGATE_JAVA"))))
NATIVE_REASON = ("Set CBUS_UNITSPEC_DIR plus CBUS_CGATE_TEST_HOST, or CBUS_NATIVE_SERVICE_BACKEND=local "
                 "with CBUS_CGATE_JAVA, for native preset acceptance")
FAMILY_RECEIPT = Path(__file__).resolve().parents[1] / "research/fixtures/key-preset-family-equivalence.json"


@contextmanager
def native_endpoint():
    """Yield an owned loopback C-Gate, or the explicitly configured disposable server."""
    if os.environ.get("CBUS_NATIVE_SERVICE_BACKEND") == "local":
        from research.local_cgate import LocalCGate
        vendor = os.environ.get("CBUS_LOCAL_CGATE_VENDOR", Path(__file__).resolve().parents[1] / "research/vendor/cgate/app")
        service = LocalCGate(vendor, java=os.environ["CBUS_CGATE_JAVA"])
        # Project deletion needs the administrative level on the owned instance.
        (service.work / "config/access.txt").write_text("interface 127.0.0.1 Clipsal\n")
        with service:
            yield "127.0.0.1", service.port
    else:
        yield os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))


@contextmanager
def closed_network_project(client, prefix):
    """Create a disposable project whose CNI target is an owned idle listener."""
    project = prefix + uuid4().hex[:8 - len(prefix)].upper()
    sentinel = socket.socket()
    sentinel.bind(("127.0.0.1", 0)); sentinel.listen(1)
    client.command("PROJECT NEW " + project)
    try:
        client.command("PROJECT USE " + project)
        client.command(f"DBCREATENET 254 Preset_Offline Cni 127.0.0.1:{sentinel.getsockname()[1]}")
        client.command("NET LOAD DB " + project)
        client.command("PROJECT SAVE " + project)
        yield project
    finally:
        try:
            client.command("PROJECT CLOSE " + project)
            client.command("PROJECT DELETE " + project)
        finally:
            sentinel.close()


def family_catalog(family, filename):
    row = next(row for row in json.loads(FAMILY_RECEIPT.read_text())["families"][family]["types"]
               if row["spec_filename"] == filename)
    return row["catalog_selection"]["firmware"], row["catalog_selection"]["catalog_numbers"][0]


def sentinel_value(spec, name, current):
    """Choose a valid value different from the current one for preservation checks."""
    parameter = spec.get(name)
    values = list(_numbers(current))
    limit = _numbers(parameter.fields.get("MaxValue") or str((1 << parameter.bit_size) - 1))[0]
    values[0] = values[0] + 1 if values[0] < limit else values[0] - 1
    if not parameter.validate_value(values)["valid"]:
        raise AssertionError("No valid sentinel for " + name)
    return " ".join(map(str, values))


def unrelated(values, workflow):
    return {name: value for name, value in values.items() if name not in workflow}


@unittest.skipUnless(NATIVE, NATIVE_REASON)
class NativeMacroTests(unittest.TestCase):
    def test_every_preset_native_values_bytes_and_database_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.programming import Programmer
        store = UnitSpecStore(os.environ["CBUS_UNITSPEC_DIR"])
        keys = ClassicKeys(store.load("KEY4.xml"))
        project = "K" + uuid4().hex[:7].upper()
        with native_endpoint() as (host, port), CGateClient(host, port=port, timeout=20) as client:
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
                            options = options_for(preset)
                            application = trigger_ready(self, keys, session, preset, 2, group=17, **options)
                            result = keys.configure(session, key=2, preset=preset, group=17, **options)
                            self.assertTrue(result["verified"])
                            actual = session.values()
                            self.assertEqual(tuple(int(actual[name].split()[1], 0) for name in STAGES), vector)
                            raw = session.get_raw_data(0x34, 2).lines[-1].split("RawData=", 1)[1]
                            self.assertEqual(raw, bytes([vector[0] << 4 | vector[1], vector[2] << 4 | vector[3]]).hex())
                            if application is not None:
                                session.set("Application", application)
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

    def test_family_types_every_preset_guarded_preservation_and_project_reload(self):
        """All 18 presets on each newly admitted classic type through native PP."""
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        store = UnitSpecStore(os.environ["CBUS_UNITSPEC_DIR"])
        report = {"format": "cbus-classic-key-family-acceptance-v1", "types": [], "passed": False}
        with native_endpoint() as (host, port), CGateClient(host, port=port, timeout=30) as client, \
                closed_network_project(client, "KF") as project:
            report["greeting"] = client.greeting
            network, programmer = f"//{project}/254", Programmer(client)
            finals = {}
            for index, unit_type in enumerate(("KEYIR1", "KEYIR4", "KEYAUX4", "DINAUX4", "KEYBC2", "KEYBC4")):
                keys = ClassicKeys(store.load(unit_type + ".xml"))
                firmware, catalog = family_catalog("classic", unit_type + ".xml")
                path, key = f"{network}/p/{230 + index}", keys.key_count
                NativeDatabase(client).create_unit(network, 230 + index, "Family_" + str(index), unit_type,
                                                   firmware, catalog_number=catalog)
                with programmer.load(network, "/db" + path) as session:
                    session.reset_defaults()
                    session.set("Application", "56 255")
                    guarded = {name: sentinel_value(keys.spec, name, value)
                               for name, value in session.values().items() if name in keys.guarded}
                    for name, value in guarded.items():
                        session.set(name, value)
                    baseline = session.values()
                    self.assertEqual({name: _numbers(baseline[name]) for name in guarded},
                                     {name: _numbers(value) for name, value in guarded.items()})
                    passed = refused = 0
                    for preset, vector in VECTORS.items():
                        with self.subTest(unit_type=unit_type, preset=preset):
                            before = session.values()
                            options = options_for(preset)
                            if preset in keys.excluded_presets:
                                with self.assertRaisesRegex(MacroError, "AUX subset"):
                                    keys.configure(session, key=key, preset=preset, group=17, **options)
                                self.assertEqual(session.values(), before)
                                refused += 1
                                continue
                            application = trigger_ready(self, keys, session, preset, key, group=17, **options)
                            self.assertTrue(keys.configure(session, key=key, preset=preset, group=17, **options)["verified"])
                            actual = session.values()
                            self.assertEqual(tuple(int(actual[name].split()[key - 1], 0) for name in STAGES), vector)
                            raw = session.get_raw_data(0x32 + 2 * (key - 1), 2).lines[-1].split("RawData=", 1)[1]
                            self.assertEqual(raw, bytes([vector[0] << 4 | vector[1], vector[2] << 4 | vector[3]]).hex())
                            self.assertEqual(unrelated(actual, _READ_FIELDS), unrelated(baseline, _READ_FIELDS))
                            if application is not None:
                                session.set("Application", application)
                            passed += 1
                    keys.configure(session, key=key, preset="timer", group=31, timer_seconds=300, expiry="ramp_off",
                                   recall1=64, recall2=128)
                    finals[path] = session.values()
                    self.assertEqual(unrelated(finals[path], _READ_FIELDS), unrelated(baseline, _READ_FIELDS))
                    self.assertEqual({name: _numbers(finals[path][name]) for name in guarded},
                                     {name: _numbers(value) for name, value in guarded.items()})
                    session.save_to_source()
                report["types"].append({"unit_type": unit_type, "firmware": firmware, "catalog_number": catalog,
                                        "key": key, "presets_passed": passed, "presets_refused": refused,
                                        "guarded_preserved": sorted(guarded)})
            client.command("PROJECT SAVE " + project)
            client.command("PROJECT CLOSE " + project)
            client.command("PROJECT LOAD " + project)
            client.command("PROJECT USE " + project)
            for path, expected in finals.items():
                with self.subTest(reload=path), programmer.load(network, "/db" + path) as session:
                    self.assertEqual(session.values(), expected)
            report["project_close_reload_passed"] = True
            report["passed"] = True
        if os.environ.get("CBUS_CLASSIC_FAMILY_REPORT"):
            Path(os.environ["CBUS_CLASSIC_FAMILY_REPORT"]).write_text(json.dumps(report, indent=2) + "\n")

    def test_native_sessions_refuse_cross_type_plans_before_writes(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        store = UnitSpecStore(os.environ["CBUS_UNITSPEC_DIR"])
        with native_endpoint() as (host, port), CGateClient(host, port=port, timeout=30) as client, \
                closed_network_project(client, "KR") as project:
            network = f"//{project}/254"
            firmware, catalog = family_catalog("classic", "KEYIR4.xml")
            NativeDatabase(client).create_unit(network, 240, "Refuse", "KEYIR4", firmware, catalog_number=catalog)
            with Programmer(client).load(network, f"/db{network}/p/240") as session:
                before = session.values()
                key4 = ClassicKeys(store.load("KEY4.xml"))
                with self.assertRaisesRegex(MacroError, "unit type differs"):
                    key4.apply(session, key4.plan(before, key=1, preset="on"))
                self.assertEqual(session.values(), before)
            for filename in ("BCNC4A.xml", "KEYV1SP.xml"):
                with self.subTest(spec=filename), self.assertRaises(MacroError):
                    ClassicKeys(store.load(filename))


if __name__ == "__main__":
    unittest.main()
