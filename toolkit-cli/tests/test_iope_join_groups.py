"""Original-derived JOIN selector vectors, graph conflicts and bounded staging."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import unittest

from cbus_toolkit.iope_join_groups import (
    CACHE_FORMAT, FORMAT, GROUPS, LAYOUTS, PROFILES, WRITABLE, IopeJoinGroups, plan_from_dict)
from cbus_toolkit.memory import MemoryImage
from cbus_toolkit.pp_editor import PPApplyError, PPEditError
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec
from test_macros import Session

DEFAULTS = {"Application": [56, 57], "InputGroupAddress": list(range(10, 18)),
            "FirstJoinPrimaryApplication": [20], "SecondJoinPrimaryApplication": [21],
            "FirstJoinEnableControlApplication": [255], "SecondJoinEnableControlApplication": [255],
            "CorridorMasterGroup": [255], "AreaGroupAddress": [22],
            "CorridorGroupBlock": [2], "FirstCorridorOfficeGroupBlock": [3],
            "SecondCorridorOfficeGroupBlock": [4]}
CACHE = {"format": CACHE_FORMAT, "source": "synthetic same-network declared object inventory",
         "applications": [{"address": app, "groups": [0, *range(10, 31), 254]} for app in (56, 57, 203)]}


def fixture(unit_type="IOPE2R2"):
    parameters = {}
    for name, (kind, address, size, bits, bit, skip) in LAYOUTS.items():
        fields = {"Name": name, "Type": kind, "Address": str(address), "ArraySize": str(size),
                  "BitAddress": str(bit), "ArraySkip": str(skip),
                  "DefaultValue": " ".join(map(str, DEFAULTS.get(name, [0] * size)))}
        if kind == "int":
            fields.update(BitSize=str(bits), MinValue="0", MaxValue=str((1 << bits) - 1))
        parameters[name] = ParameterSpec(name, kind, "synthetic.xml", fields)
    for name, address in (("RecoveryWitness", 0x1C), ("AllocationWitness", 0x7E),
                          ("SceneWitness", 0xB0), ("MacroWitness", 0xB1)):
        parameters[name] = ParameterSpec(name, "int", "synthetic.xml", {
            "Name": name, "Type": "int", "Address": str(address), "DefaultValue": "197"})
    return UnitSpec(unit_type + ".xml", {"Type": unit_type}, ("synthetic.xml",), parameters)


class JoinGroupsTest(unittest.TestCase):
    def setUp(self):
        self.editor = IopeJoinGroups(fixture())
        self.current = fixture().defaults()
        self.identity = ("IOPE2R2", "1.2.00", "5752PP/2R")

    def plan(self, **options):
        return self.editor.plan(self.current, identity=self.identity, group_cache=CACHE, **options)

    def test_both_applications_profiles_and_boundary_group_addresses(self):
        for unit_type in PROFILES:
            editor = IopeJoinGroups(fixture(unit_type))
            for app in (56, 203):
                current = fixture(unit_type).defaults()
                if app == 203:
                    current.update(FirstJoinPrimaryApplication="255", SecondJoinPrimaryApplication="255",
                                   FirstJoinEnableControlApplication="20", SecondJoinEnableControlApplication="21")
                plan = editor.plan(current, identity=(unit_type, "1.2.00", PROFILES[unit_type].catalog_number),
                                   group_cache=CACHE, first_group=0, second_group=254)
                final = {**plan.expected, **plan.changes}
                suffix = "JoinEnableControlApplication" if app == 203 else "JoinPrimaryApplication"
                self.assertEqual((final["First" + suffix], final["Second" + suffix]), ((0,), (254,)))
                self.assertLessEqual(set(plan.changes), WRITABLE)
                self.assertEqual(plan.details["selector_order"], ["first_group", "second_group"])
                self.assertFalse(plan.details["whole_dialog_save"])

    def test_unused_second_and_read_only_show(self):
        plan = self.plan(second_group=255)
        self.assertEqual(dict(plan.changes), {"SecondJoinPrimaryApplication": (255,)})
        self.current["SecondJoinPrimaryApplication"] = "255"
        self.assertEqual(self.plan(second_group=23).changes["SecondJoinPrimaryApplication"], (23,))
        self.assertFalse(self.editor.show(self.current)["group_objects_resolved"])
        self.current["FirstJoinEnableControlApplication"] = "24"
        self.assertEqual(self.editor.show(self.current)["effective_groups"][0], [203, 24])

    def test_selector_order_releases_first_before_second(self):
        plan = self.plan(first_group=23, second_group=20)
        self.assertEqual(plan.changes["SecondJoinPrimaryApplication"], (20,))
        with self.assertRaisesRegex(PPEditError, "other Join"):
            self.plan(first_group=21, second_group=23)

    def test_positive_objects_and_exact_application_identity(self):
        self.current["SecondApplicationBlocks"] = "1"
        # 57/10 differs from 56/10: the first block alone is not a conflict.
        self.assertEqual(self.plan(first_group=10).changes["FirstJoinPrimaryApplication"], (10,))
        with self.assertRaisesRegex(PPEditError, "input block"):
            self.plan(first_group=11)
        with self.assertRaisesRegex(PPEditError, "positive group object"):
            self.plan(first_group=99)
        for field in ("AreaGroupAddress", "FirstJoinPrimaryApplication", "InputGroupAddress"):
            current = deepcopy(self.current)
            current[field] = "99" if field != "InputGroupAddress" else "99 11 12 13 14 15 16 17"
            with self.assertRaisesRegex(PPEditError, "positive group object"):
                self.editor.plan(current, identity=self.identity, group_cache=CACHE, first_group=23)

    def test_area_opposite_join_and_corridor_conflicts_both_selectors(self):
        for option in ("first_group", "second_group"):
            with self.assertRaisesRegex(PPEditError, "Area group"):
                self.plan(**{option: 22})
            other = 21 if option == "first_group" else 20
            with self.assertRaisesRegex(PPEditError, "other Join"):
                self.plan(**{option: other})
            self.current["FirstCorridorLinkEnable"] = "1"
            with self.assertRaises(PPEditError):
                self.plan(**{option: 12})

    def test_admission_and_initialization_refusals(self):
        for options in ({}, {"first_group": 255}, {"first_group": True}, {"second_group": -1}):
            with self.assertRaises(PPEditError):
                self.plan(**options)
        for fields, message in (({"FirstJoinEnableControlApplication": "23"}, "Dual-populated"),
                                ({"SecondJoinPrimaryApplication": "255", "SecondJoinEnableControlApplication": "23"}, "Mixed"),
                                ({"FirstJoinPrimaryApplication": "255"}, "assigned first"),
                                ({"FirstCorridorOfficeGroupBlock": "2"}, "initialization")):
            current = {**self.current, **fields}
            with self.assertRaisesRegex(PPEditError, message):
                self.editor.plan(current, identity=self.identity, group_cache=CACHE, first_group=23)

    def test_exact_group_bytes_preserve_recovery_allocation_and_scene_memory(self):
        for control in (False, True):
            if control:
                self.current.update(FirstJoinPrimaryApplication="255", SecondJoinPrimaryApplication="255",
                                    FirstJoinEnableControlApplication="20", SecondJoinEnableControlApplication="21")
            plan = self.plan(first_group=23, second_group=24)
            before = self.editor.codec.encode_many(plan.expected).apply(MemoryImage.from_bytes(b"\xa5" * 256))
            after = self.editor.codec.encode_many(plan.changes).apply(before)
            expected = bytearray(before.read(0, 256))
            expected[0x63:0x67] = bytes([255, 255, 23, 24] if control else [23, 24, 255, 255])
            self.assertEqual(after.read(0, 256), bytes(expected))

    def test_partial_staging_failure_restores_group_fields(self):
        session = Session(fixture())
        session.firmware = "1.2.00"
        session.catalog_number = "5752PP/2R"
        session.failure = "SecondJoinPrimaryApplication"
        before = session.values()
        with self.assertRaises(PPApplyError):
            self.editor.apply(session, self.plan(first_group=23, second_group=24))
        self.assertEqual(session.values(), before)

    def test_canonical_roundtrip_stale_snapshot_and_unowned_preservation(self):
        session = Session(fixture())
        session.firmware = "1.2.00"
        session.catalog_number = "5752PP/2R"
        plan = self.plan(first_group=23, second_group=24)
        canonical = plan_from_dict(plan.as_dict())
        result = self.editor.apply(session, canonical)
        self.assertFalse(result["saved"])
        for name in ("RecoveryWitness", "AllocationWitness", "SceneWitness", "MacroWitness"):
            self.assertEqual(session.current[name], "197")
        with self.assertRaises(PPEditError):
            self.editor.apply(session, canonical)
        tampered = replace(plan, changes={"AreaGroupAddress": (23,)})
        with self.assertRaisesRegex(PPEditError, "canonical"):
            self.editor.apply(session, tampered)
        for key in ("selector_order", "projection", "join_application", "whole_dialog_save"):
            data = plan.as_dict()
            data[key] = "tampered"
            with self.assertRaises(PPEditError):
                self.editor.apply(session, plan_from_dict(data))


@unittest.skipUnless(os.environ.get("CBUS_TOOLKIT_EXE") and os.environ.get("CBUS_UNITSPEC_DIR"),
                     "Set original Toolkit EXE and decoded UnitSpecs for exact source checks")
class JoinGroupsOriginalSourceTest(unittest.TestCase):
    def test_source_bytes_strings_and_layouts(self):
        import pefile
        from cbus_toolkit.unitspec import UnitSpecStore
        receipt = json.loads((Path(__file__).resolve().parents[1] /
                              "research/fixtures/iope-join-groups-source-review.json").read_text())
        exe = Path(os.environ["CBUS_TOOLKIT_EXE"])
        data = exe.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), receipt["toolkit_exe_sha256"])
        self.assertEqual(hashlib.sha256(Path(os.environ.get("CBUS_TOOLKIT_MAP", exe.with_suffix(".map"))).read_bytes()).hexdigest(),
                         receipt["toolkit_map_sha256"])
        image = pefile.PE(data=data)
        for row in receipt["methods"]:
            start, end = int(row["start"], 16), int(row["end"], 16)
            raw = image.get_data(start - image.OPTIONAL_HEADER.ImageBase, end - start)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), row["sha256"])
        for row in receipt["strings"]:
            raw = image.get_data(int(row["start"], 16) - image.OPTIONAL_HEADER.ImageBase, row["size"])
            self.assertEqual(raw.decode("utf-16le"), row["value"])
        store = UnitSpecStore(os.environ["CBUS_UNITSPEC_DIR"])
        for unit_type in PROFILES:
            IopeJoinGroups(store.load(unit_type + ".xml"))
