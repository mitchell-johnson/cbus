"""IOPE Join Recovery original-derived scalar vectors and isolated PP safety."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
import struct
import uuid
from pathlib import Path
import unittest

from cbus_toolkit.iope_join_recovery import (
    CACHE_FORMAT, FORMAT, GROUPS, LAYOUTS, PROFILES, RECOVERY, STARTUP, STORE,
    WRITABLE, IopeJoinRecovery, plan_from_dict)
from cbus_toolkit.memory import MemoryImage
from cbus_toolkit.pp_editor import PPApplyError, PPEditError
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec
from test_macros import Session

CACHE = {"format": CACHE_FORMAT, "source": "synthetic declared same-network Join objects",
         "applications": [{"address": 56, "groups": [20, 21]}, {"address": 203, "groups": [40, 41]}]}
DEFAULTS = {"Application": [56, 255], "FirstJoinPrimaryApplication": [20],
            "SecondJoinPrimaryApplication": [21], "FirstJoinEnableControlApplication": [255],
            "SecondJoinEnableControlApplication": [255]}
# Four low bits are the startup flags in original member order. The fifth
# bit is store. These literals transcribe the original branch outcomes.
LOAD_VECTOR = ("first-join", "first-join", "second-join", "quad-join", "first-join", "first-join",
               "quad-join", "quad-join", "second-join", "quad-join", "second-join", "quad-join",
               "quad-join", "quad-join", "quad-join", "quad-join") + ("restore",) * 16
SAVE_VECTOR = {56: {"first-join": 1, "second-join": 2, "quad-join": 3, "restore": 16},
               203: {"first-join": 4, "second-join": 8, "quad-join": 12, "restore": 16}}


def fixture(unit_type="IOPE2R2"):
    parameters = {}
    for name, (kind, address, size, bits, bit, skip) in LAYOUTS.items():
        fields = {"Name": name, "Type": kind, "Address": str(address), "ArraySize": str(size),
                  "BitAddress": str(bit), "ArraySkip": str(skip),
                  "DefaultValue": " ".join(map(str, DEFAULTS.get(name, [0] * size)))}
        if kind == "int":
            fields.update(BitSize=str(bits), MinValue="0", MaxValue=str((1 << bits) - 1))
        parameters[name] = ParameterSpec(name, kind, "synthetic.xml", fields)
    for name, address, value in (("SceneData", 0x70, 197), ("AllocationData", 0x71, 211)):
        parameters[name] = ParameterSpec(name, "int", "synthetic.xml", {
            "Name": name, "Type": "int", "Address": str(address), "DefaultValue": str(value)})
    return UnitSpec(unit_type + ".xml", {"Type": unit_type}, ("synthetic.xml",), parameters)


def session(unit_type="IOPE2R2"):
    result = Session(fixture(unit_type))
    result.firmware = "1.2.00"
    result.catalog_number = PROFILES[unit_type].catalog_number
    return result


class JoinRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.editor = IopeJoinRecovery(fixture())
        self.current = fixture().defaults()
        self.identity = ("IOPE2R2", "1.2.00", "5752PP/2R")

    def plan(self, recovery="first-join", **options):
        return self.editor.plan(self.current, identity=self.identity, group_cache=CACHE,
                                recovery=recovery, **options)

    def seed(self, mask):
        for index, name in enumerate((*STARTUP, STORE)):
            self.current[name] = str((mask >> index) & 1)

    def enable_application(self):
        self.current.update(FirstJoinPrimaryApplication="255", SecondJoinPrimaryApplication="255",
                            FirstJoinEnableControlApplication="40", SecondJoinEnableControlApplication="41")

    def test_all_32_original_load_vectors(self):
        for mask, recovery in enumerate(LOAD_VECTOR):
            self.seed(mask)
            self.assertEqual(self.editor.show(self.current)["recovery"], recovery, mask)
        self.assertEqual(self.editor.show(self.current)["choices"], list(RECOVERY))
        self.assertFalse(self.editor.show(self.current)["group_objects_resolved"])

    def test_256_save_vectors_and_shared_neighbour_bits(self):
        for application in (56, 203):
            if application == 203:
                self.enable_application()
            for before in range(32):
                self.seed(before)
                for recovery, expected in SAVE_VECTOR[application].items():
                    with self.subTest(application=application, before=before, recovery=recovery):
                        plan = self.plan(recovery)
                        final = {**plan.expected, **plan.changes}
                        actual = sum(final[name][0] << index for index, name in enumerate((*STARTUP, STORE)))
                        self.assertEqual(actual, expected)
                        self.assertLessEqual(set(plan.changes), WRITABLE)
                        self.assertEqual(plan.details["join_application"], application)
                        original = MemoryImage({0x1C: 0xC3 | ((before & 15) << 2),
                                                0x3E: 0x7F | ((before >> 4) << 7)})
                        result = self.editor.codec.encode_many(plan.changes).apply(original)
                        self.assertEqual(result.byte(0x1C), 0xC3 | ((expected & 15) << 2))
                        self.assertEqual(result.byte(0x3E), 0x7F | ((expected >> 4) << 7))
                        for name in GROUPS:
                            self.assertEqual(final[name], plan.expected[name])

    def test_first_join_only_eligible_second_only_disabled(self):
        self.current["SecondJoinPrimaryApplication"] = "255"
        for recovery in RECOVERY:
            self.plan(recovery)
        self.current.update(FirstJoinPrimaryApplication="255", SecondJoinPrimaryApplication="21")
        with self.assertRaisesRegex(PPEditError, "disabled without.*first"):
            self.plan("restore")
        self.current["SecondJoinPrimaryApplication"] = "255"
        with self.assertRaisesRegex(PPEditError, "disabled without.*first"):
            self.plan("first-join")

    def test_mixed_and_dual_application_states_refused(self):
        cases = ({"FirstJoinEnableControlApplication": "40"},
                 {"SecondJoinEnableControlApplication": "41"},
                 {"SecondJoinPrimaryApplication": "255", "SecondJoinEnableControlApplication": "41"},
                 {"FirstJoinPrimaryApplication": "255", "FirstJoinEnableControlApplication": "40"})
        for fields in cases:
            pp = session()
            pp.current.update(fields)
            with self.subTest(fields=fields), self.assertRaisesRegex(PPEditError, "full group workflow"):
                self.editor.configure(pp, group_cache=CACHE, recovery="restore")
            self.assertEqual(pp.calls, [])

    def test_positive_metadata_required_for_consumed_objects(self):
        for cache in (None, {**CACHE, "source": ""}, {**CACHE, "applications": []},
                      {**CACHE, "applications": [{"address": 56, "groups": [20]}]},
                      {**CACHE, "applications": [{"address": 56, "groups": [21]}]}):
            with self.subTest(cache=cache), self.assertRaises(PPEditError):
                self.editor.plan(self.current, identity=self.identity, recovery="first-join", group_cache=cache)
        self.current["Application"] = "202 255"
        with self.assertRaisesRegex(PPEditError, "primary Lighting"):
            self.plan()

    def test_exact_profiles_firmware_catalogue_and_layouts(self):
        for unit_type in PROFILES:
            editor = IopeJoinRecovery(fixture(unit_type))
            for firmware in ("1.0.00", "1.1.00", "1.2.00", "1.2.99"):
                editor.plan(fixture(unit_type).defaults(), identity=(unit_type, firmware, None),
                            group_cache=CACHE, recovery="restore")
            for firmware in (None, "9", "1.3.00", "0.9.99"):
                with self.assertRaises(PPEditError):
                    editor.plan(fixture(unit_type).defaults(), identity=(unit_type, firmware, None),
                                group_cache=CACHE, recovery="restore")
        for identity in (None, self.identity[:2], ("IOPE2R2", "1.2.00", "wrong")):
            with self.assertRaises(PPEditError):
                self.editor.plan(self.current, identity=identity, group_cache=CACHE, recovery="first-join")
        with self.assertRaises(PPEditError):
            IopeJoinRecovery(fixture(), "IOPE1R1")
        p = fixture().get(STORE)
        bad = replace(p, fields={**p.fields, "BitAddress": "6"})
        with self.assertRaisesRegex(PPEditError, "Unsupported parameter layout"):
            IopeJoinRecovery(replace(fixture(), parameters={**fixture().parameters, STORE: bad}))

    def test_choices_fail_closed(self):
        for value in (None, True, 1, "on", "off", "both", "quad"):
            with self.subTest(value=value), self.assertRaises(PPEditError):
                self.plan(value)

    def test_apply_roundtrip_preservation_stale_schema_and_rollback(self):
        pp = session()
        plan = self.editor.plan(pp.values(), identity=self.identity, group_cache=CACHE, recovery="quad-join")
        result = self.editor.apply(pp, plan_from_dict(json.loads(json.dumps(plan.as_dict()))))
        self.assertTrue(result["verified"])
        self.assertFalse(result["saved"])
        self.assertEqual((pp.current["SceneData"], pp.current["AllocationData"]), ("197", "211"))
        with self.assertRaisesRegex(PPEditError, "changed since"):
            self.editor.apply(pp, plan)
        pp = session()
        pp.current["Application"] = "56 57"
        with self.assertRaisesRegex(PPEditError, "changed since"):
            self.editor.apply(pp, plan)
        self.assertEqual(pp.calls, [])
        pp = session()
        before = pp.values()
        pp.failure = STARTUP[1]
        with self.assertRaises(PPApplyError):
            self.editor.apply(pp, plan)
        self.assertEqual(pp.values(), before)

    def test_forged_saved_plans_rejected_without_writes(self):
        doc = self.plan("quad-join").as_dict()
        for edits in ({"saved": True}, {"extra": True}, {"whole_dialog_save": True},
                      {"join_application": 203}, {"firmware": "1.1.00"},
                      {"changes": {STARTUP[0]: [True]}}, {"changes": {STARTUP[0]: [1.0]}},
                      {"changes": {"FirstJoinPrimaryApplication": [21]}},
                      {"options": {"recovery": "restore", "group_cache": CACHE}}):
            pp = session()
            with self.subTest(edits=edits), self.assertRaises(PPEditError):
                self.editor.apply(pp, plan_from_dict({**deepcopy(doc), **edits}))
            self.assertEqual(pp.calls, [])
        del doc["saved"]
        with self.assertRaises(PPEditError):
            plan_from_dict(doc)

    def test_receipt_pins_control_binding_predicate_and_save_boundary(self):
        root = Path(__file__).resolve().parents[1]
        r = json.loads((root / "research/fixtures/iope-join-recovery-source-review.json").read_text())
        self.assertFalse(r["original_execution"])
        self.assertTrue(r["eligibility"]["first_join_required"])
        self.assertFalse(r["eligibility"]["second_join_alone_sufficient"])
        self.assertEqual(r["save"]["raw_masks"], {"0x1c": "0x3c", "0x3e": "0x80"})
        self.assertEqual(r["recovery_ordinals"], list(RECOVERY))
        self.assertEqual(FORMAT, "cbus-iope-join-recovery-plan-v1")


@unittest.skipUnless(os.environ.get("CBUS_TOOLKIT_EXE") and os.environ.get("CBUS_UNITSPEC_DIR"),
                     "Set owned original Toolkit EXE and decoded UnitSpecs for exact source checks")
class JoinRecoveryOriginalSourceTest(unittest.TestCase):
    def test_exact_interface_table_thunks_strings_methods_and_specs(self):
        import pefile
        from cbus_toolkit.unitspec import UnitSpecStore
        root = Path(__file__).resolve().parents[1]
        r = json.loads((root / "research/fixtures/iope-join-recovery-source-review.json").read_text())
        exe = Path(os.environ["CBUS_TOOLKIT_EXE"])
        data = exe.read_bytes()
        mapping = Path(os.environ.get("CBUS_TOOLKIT_MAP", exe.with_suffix(".map"))).read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), r["toolkit_exe_sha256"])
        self.assertEqual(hashlib.sha256(mapping).hexdigest(), r["toolkit_map_sha256"])
        image = pefile.PE(data=data)
        base = image.OPTIONAL_HEADER.ImageBase
        for method in r["methods"]:
            start, end = int(method["start"], 16), int(method["end"], 16)
            self.assertEqual(hashlib.sha256(image.get_data(start - base, end - start)).hexdigest(), method["sha256"])
        for raw in (*r["raw_ranges"], *r["strings"]):
            data = image.get_data(int(raw["start"], 16) - base, raw["size"])
            self.assertEqual(hashlib.sha256(data).hexdigest(), raw["sha256"])
            if "value" in raw:
                self.assertEqual(data.decode("utf-16-le"), raw["value"])
        # Independently follow the original Delphi ancestry, rather than
        # accepting the receipt's first-interface-only predicate by assertion.
        read = lambda address, size: image.get_data(address - base, size)
        integer = lambda address: struct.unpack("<I", read(address, 4))[0]
        ancestry = r["eligibility"]["inheritance"]
        fallback = r["eligibility"]["fallback_interface_guid"]
        for unit_type, anchor in (("IOPE1R1", 0xD542B0), ("IOPE2R2", 0xD544DC),
                                  ("IOPE2C4", 0xD54708)):
            actual, seen, address = [], set(), integer(anchor)
            while address:
                self.assertNotIn(address, seen)
                seen.add(address)
                actual.append(hex(address))
                record = ancestry["classes"][hex(address)]
                parent, interface = integer(address - 48), integer(address - 84)
                self.assertEqual(hex(parent), record["parent_reference"])
                self.assertEqual(hex(interface), record["interface_table"])
                name = integer(address - 56)
                self.assertEqual(read(name + 1, read(name, 1)[0]).decode(), record["name"])
                guids = [str(uuid.UUID(bytes_le=read(interface + 4 + index * 28, 16)))
                         for index in range(integer(interface))] if interface else []
                self.assertEqual(guids, record["interface_guids"])
                self.assertNotIn(fallback, guids)
                address = integer(parent) if parent else 0
            self.assertEqual(actual, ancestry["profile_chains"][unit_type])
        directory = Path(os.environ["CBUS_UNITSPEC_DIR"])
        for name, digest in r["unitspec_sha256"].items():
            self.assertEqual(hashlib.sha256((directory / name).read_bytes()).hexdigest(), digest)
        store = UnitSpecStore(directory)
        for unit_type in PROFILES:
            IopeJoinRecovery(store.load(unit_type + ".xml"))


if __name__ == "__main__":
    unittest.main()
