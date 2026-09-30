"""Independent IOPE Logic source vectors and bounded PP transaction checks."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from cbus_toolkit.iope_logic import CACHE_FORMAT, FORMAT, LAYOUTS, PROFILES, IopeLogic, plan_from_dict
from cbus_toolkit.memory import MemoryImage
from cbus_toolkit.pp_editor import PPApplyError, PPEditError
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec
from test_macros import Session

# Independently transcribed original I_IOPE geometry. Extra parameters exercise
# shared-bit and out-of-scope preservation rather than mirroring LAYOUTS.
ROWS = {
    "Application": ("int", 0x21, 2, 8, 0, "56 255"),
    "OutputGroupAddress": ("int", 0x58, 4, 8, 0, "10 11 12 13"),
    "OutputLogicGroupAddress": ("int", 0x5C, 4, 8, 0, "20 21 22 23"),
    "LogicGA13Associations": ("int", 0x70, 4, 1, 0, "1 0 0 0"),
    "LogicGA14Associations": ("int", 0x70, 4, 1, 1, "0 0 0 0"),
    "LogicGA15Associations": ("int", 0x70, 4, 1, 2, "0 0 0 0"),
    "LogicGA16Associations": ("int", 0x70, 4, 1, 3, "0 0 0 0"),
    "LogicFunction": ("int", 0x70, 4, 1, 7, "1 0 1 0"),
    "LevelStoreEnable": ("bit", 0x6E, 4, 1, 0, "0 1 0 1"),
    "LogicLevelStoreEnable": ("bit", 0x6E, 4, 1, 4, "0 1 0 1"),
    "LightLevelOutput": ("int", 0x08, 8, 8, 0, "10 20 30 40 50 60 70 80"),
    "RestrikeChannel": ("int", 0x70, 4, 1, 6, "1 1 1 1"),
    "UnitAddress": ("int", 0x20, 1, 8, 0, "37"),
}


def fixture(unit_type="IOPE2C4"):
    params = {}
    for name, (kind, address, count, bits, bit, default) in ROWS.items():
        fields = {"Name": name, "Type": kind, "Address": str(address), "ArraySize": str(count),
                  "BitSize": str(bits), "BitAddress": str(bit), "ArraySkip": "0", "DefaultValue": default,
                  "MinValue": "0", "MaxValue": str((1 << bits) - 1)}
        params[name] = ParameterSpec(name, kind, "synthetic-iope-logic.xml", fields)
    return UnitSpec(unit_type + ".xml", {"Type": unit_type}, ("synthetic-iope-logic.xml",), params)


def session(unit_type="IOPE2C4", firmware="1.2.00"):
    pp = Session(fixture(unit_type))
    pp.firmware, pp.catalog_number = firmware, PROFILES[unit_type].catalog_number
    return pp


def cache(groups=None):
    return {"format": CACHE_FORMAT, "source": "synthetic test object inventory",
            "applications": [{"address": 56, "groups": list(range(10, 31)) if groups is None else groups}]}


class IopeLogicTest(unittest.TestCase):
    def setUp(self):
        self.pp = session()
        self.editor = IopeLogic(self.pp.spec)
        self.identity = (self.pp.unit_type, self.pp.firmware, self.pp.catalog_number)

    def plan(self, **options):
        return self.editor.plan(self.pp.values(), identity=self.identity, group_cache=cache(), **options)

    def test_profiles_identity_and_layout(self):
        for unit_type in PROFILES:
            pp = session(unit_type)
            editor = IopeLogic(pp.spec)
            for fw in ("1.0.00", "1.1.00", "1.2.99"):
                editor.plan(pp.values(), identity=(unit_type, fw, pp.catalog_number), group_cache=cache())
            shown = editor.show(pp.values())
            self.assertEqual(len(shown["channels"]), PROFILES[unit_type].outputs)
            self.assertEqual(len(shown["logic_groups"]), 4)
        for identity in (None, ("IOPE2C4", None, None), ("IOPE2C4", "1.3.00", None),
                         ("IOPE2C4", "1.2.00", "5752PP/1R"), ([], "1.2.00", None)):
            with self.subTest(identity=identity), self.assertRaises(PPEditError):
                self.editor.plan(self.pp.values(), identity=identity, group_cache=cache())
        wrong = fixture()
        fields = dict(wrong.get("LogicFunction").fields, BitAddress="6")
        wrong.parameters["LogicFunction"] = replace(wrong.get("LogicFunction"), fields=fields)
        with self.assertRaisesRegex(PPEditError, "layout"):
            IopeLogic(wrong)
        with self.assertRaisesRegex(PPEditError, "matching"):
            IopeLogic(fixture("IOPE1R1"), "IOPE2C4")

    def test_associations_replace_and_or_for_dimmer_too(self):
        plan = self.plan(channels={3: {"logic_groups": [4, 2], "logic_function": "and"}})
        self.assertEqual(dict(plan.changes), {"LogicGA14Associations": (0, 0, 1, 0),
                                             "LogicGA16Associations": (0, 0, 1, 0),
                                             "LogicFunction": (1, 0, 0, 0)})
        self.assertEqual(plan.details["options"]["channels"]["3"]["logic_groups"], [2, 4])
        self.assertFalse(plan.details["recovery_modal_opened"])
        self.assertEqual(plan.details["derived"], [])
        with self.assertRaisesRegex(PPEditError, "including dimmer"):
            self.plan(channels={3: {"logic_groups": [1], "logic_function": "min"}})
        for function, raw in (("and", 0), ("or", 1)):
            plan = self.plan(channels={3: {"logic_groups": [1], "logic_function": function}})
            self.assertEqual({**plan.expected, **plan.changes}["LogicFunction"][2], raw)

    def test_disabled_controls_retain_hidden_values(self):
        plan = self.plan(channels={1: {"logic_groups": []}})
        self.assertEqual(dict(plan.changes), {"LogicGA13Associations": (0, 0, 0, 0)})
        with self.assertRaisesRegex(PPEditError, "disables logic_function"):
            self.plan(channels={1: {"logic_groups": [], "logic_function": "and"}})
        with self.assertRaisesRegex(PPEditError, "disables group_address"):
            self.plan(logic_groups={2: {"group_address": 25}})
        pp = session("IOPE1R1")
        pp.current["LogicGA14Associations"] = "0 1 1 1"
        with self.assertRaisesRegex(PPEditError, "disables group_address"):
            IopeLogic(pp.spec).plan(pp.values(), identity=(pp.unit_type, pp.firmware, None),
                                    group_cache=cache(), logic_groups={2: {"group_address": 25}})
        # Unused group255 is an allowed stored/selected object; do not import
        # a different unit family's validation against its association.
        plan = self.plan(logic_groups={1: {"group_address": 255}})
        self.assertEqual(dict(plan.changes), {"OutputLogicGroupAddress": (255, 21, 22, 23)})

    def test_group_selection_copies_logic_peer_raw_without_modal(self):
        plan = self.plan(logic_groups={1: {"group_address": 21}})
        self.assertEqual(plan.changes["LightLevelOutput"], (10, 20, 30, 40, 60, 60, 70, 80))
        self.assertEqual(plan.changes["LogicLevelStoreEnable"], (1, 1, 0, 1))
        self.assertFalse(plan.details["recovery_modal_opened"])
        self.assertEqual(plan.details["derived"], [{"logic_group": 1, "copied_from_logic_group": 1},
                                                  {"logic_group": 1, "copied_from_logic_group": 2}])

    def test_group_cascade_includes_self_and_last_match_wins(self):
        self.pp.current["OutputLogicGroupAddress"] = "20 21 20 20"
        self.pp.current["LogicGA14Associations"] = "1 0 0 0"
        plan = self.plan(logic_groups={2: {"group_address": 20}})
        # row1->row2 then self reads mutated row2, then row3 then row4.
        self.assertEqual(plan.changes["LightLevelOutput"], (10, 20, 30, 40, 50, 80, 70, 80))
        self.assertEqual([row["copied_from_logic_group"] for row in plan.details["derived"]], [1, 2, 3, 4])
        self.pp.current["OutputLogicGroupAddress"] = "20 21 22 23"
        plan = self.plan(logic_groups={2: {"group_address": 20}})
        self.assertEqual(plan.changes["LightLevelOutput"][5], 50)  # self must not restore original60

    def test_last_active_output_wins_and_same_address_reruns(self):
        for unit_type, level, store in (("IOPE1R1", 10, 0), ("IOPE2R2", 20, 1), ("IOPE2C4", 40, 1)):
            pp = session(unit_type)
            pp.current["OutputGroupAddress"] = "10 10 10 10"
            pp.current["OutputLogicGroupAddress"] = "10 21 22 10"
            editor = IopeLogic(pp.spec)
            plan = editor.plan(pp.values(), identity=(unit_type, pp.firmware, None), group_cache=cache(),
                               logic_groups={1: {"group_address": 10}})
            self.assertNotIn("OutputLogicGroupAddress", plan.changes)  # equal setter still copies
            self.assertEqual(plan.changes["LightLevelOutput"][4], level)
            self.assertEqual({**plan.expected, **plan.changes}["LogicLevelStoreEnable"][0], store)
            self.assertEqual(plan.details["derived"][-1], {"logic_group": 1, "copied_from_channel": PROFILES[unit_type].outputs})

    def test_group_setters_have_ascending_order_before_recovery(self):
        plan = self.plan(channels={1: {"logic_groups": [1, 2]}},
                         logic_groups={2: {"group_address": 20}, 1: {"group_address": 21, "recovery_percent": 50, "level_store": False}})
        self.assertEqual(plan.changes["OutputLogicGroupAddress"], (21, 20, 22, 23))
        # group1 takes row2's60/store1; group2 now has no20 peer and keeps60.
        # Then modal normalizes60->61; explicit group1 slider50%->127.
        self.assertEqual(plan.changes["LightLevelOutput"], (10, 20, 30, 40, 127, 61, 71, 81))
        self.assertEqual({**plan.expected, **plan.changes}["LogicLevelStoreEnable"], (0, 1, 0, 1))
        self.assertEqual(plan.details["derived"][-1], {"recovery_modal_initialization": [1, 2, 3, 4]})

    def test_modal_normalizes_all_four_even_unused_and_unassociated(self):
        self.pp.current["OutputLogicGroupAddress"] = "255 255 255 255"
        self.pp.current["LightLevelOutput"] = "10 20 30 40 179 51 77 89"
        plan = self.plan(logic_groups={4: {"level_store": True}})
        self.assertEqual(dict(plan.changes), {"LightLevelOutput": (10, 20, 30, 40, 178, 51, 76, 89)})
        self.assertTrue(plan.details["recovery_modal_opened"])
        # Store true preserves rounded89, never the output-channel255 sentinel.
        self.assertEqual(plan.changes["LightLevelOutput"][7], 89)
        self.assertEqual(plan.details["derived"], [{"recovery_modal_initialization": [1, 2, 3, 4]}])

    def test_recovery_store_enabling_and_slider_bounds(self):
        for percent, raw in ((0, 0), (50, 127), (100, 255)):
            plan = self.plan(logic_groups={2: {"level_store": False, "recovery_percent": percent}})
            self.assertEqual(plan.changes["LightLevelOutput"][5], raw)
            self.assertEqual(plan.changes["LogicLevelStoreEnable"], (0, 0, 0, 1))
        with self.assertRaisesRegex(PPEditError, "disables recovery_percent"):
            self.plan(logic_groups={2: {"recovery_percent": 20}})
        with self.assertRaisesRegex(PPEditError, "disables recovery_percent"):
            self.plan(logic_groups={1: {"level_store": True, "recovery_percent": 20}})
        # Changing a row's recovery does not propagate to another same-group row.
        self.pp.current["OutputLogicGroupAddress"] = "20 20 20 20"
        plan = self.plan(logic_groups={1: {"recovery_percent": 100}})
        self.assertEqual(plan.changes["LightLevelOutput"], (10, 20, 30, 40, 255, 61, 71, 81))

    def test_positive_cache_consumes_only_active_output_objects(self):
        pp = session("IOPE1R1")
        editor = IopeLogic(pp.spec)
        kwargs = {"identity": (pp.unit_type, pp.firmware, None)}
        editor.plan(pp.values(), **kwargs, group_cache=cache([10, 20, 21, 22, 23]))
        for groups in ([20, 21, 22, 23], [10, 20, 21, 22]):
            with self.assertRaisesRegex(PPEditError, "positive group object"):
                editor.plan(pp.values(), **kwargs, group_cache=cache(groups))
        with self.assertRaisesRegex(PPEditError, "positive group object"):
            editor.plan(pp.values(), **kwargs, group_cache=cache([10, 20, 21, 22, 23]),
                        logic_groups={1: {"group_address": 24}})
        invalid = cache()
        invalid["applications"][0]["address"] = 57
        with self.assertRaisesRegex(PPEditError, "primary application"):
            editor.plan(pp.values(), **kwargs, group_cache=invalid)
        pp.current["Application"] = "202 255"
        with self.assertRaisesRegex(PPEditError, "Lighting"):
            editor.plan(pp.values(), **kwargs, group_cache=cache())

    def test_invalid_domains_and_metadata_fail_without_mutation(self):
        before = self.pp.values()
        for options in ({"channels": {True: {"logic_groups": [1]}}}, {"channels": {5: {"logic_groups": []}}},
                        {"channels": {1: {"logic_groups": [1, 1]}}}, {"channels": {1: {"logic_groups": [True]}}},
                        {"channels": {1: {"logic_groups": [0]}}}, {"channels": {1: {"logic_function": 0}}},
                        {"logic_groups": {0: {"group_address": 1}}}, {"logic_groups": {1: {"group_address": 256}}},
                        {"logic_groups": {1: {"level_store": 1}}}, {"logic_groups": {1: {"recovery_percent": 101}}},
                        {"logic_groups": {1: {"recovery_percent": True}}}, {"logic_groups": {1: {"raw_level": 1}}},
                        {"channels": []}, {"logic_groups": {1: {}}}):
            with self.subTest(options=options), self.assertRaises(PPEditError):
                self.plan(**options)
        for bad in (None, {}, cache([10, 10]), cache([True]), cache([255])):
            with self.subTest(cache=bad), self.assertRaises(PPEditError):
                self.editor.plan(before, identity=self.identity, group_cache=bad)
        self.assertEqual(self.pp.values(), before)
        self.assertEqual(self.pp.calls, [])

    def test_inactive_slots_shared_bits_and_readonly_fields_preserved(self):
        for unit_type in PROFILES:
            pp = session(unit_type)
            editor = IopeLogic(pp.spec)
            image = editor.codec.encode_many({name: list(map(int, value.split())) for name, value in pp.values().items()}).apply(
                MemoryImage.from_bytes(bytes([0x35]) * 256))
            plan = editor.plan(pp.values(), identity=(unit_type, pp.firmware, None), group_cache=cache(),
                               channels={1: {"logic_groups": [2, 4], "logic_function": "and"}},
                               logic_groups={1: {"level_store": True}})
            after = editor.codec.encode_many(plan.changes).apply(image)
            for address in range(256):
                mask = 0x8F if address == 0x70 else 0x10 if address == 0x6E else 0xFF if 0x0C <= address <= 0x0F else 0
                self.assertEqual(after.byte(address) & ~mask, image.byte(address) & ~mask, (unit_type, address))
            self.assertTrue(set(plan.changes).isdisjoint({"Application", "OutputGroupAddress", "LevelStoreEnable"}))
            self.assertEqual({**plan.expected, **plan.changes}["LightLevelOutput"][:4], (10, 20, 30, 40))

    def test_safe_replay_stale_identity_and_forged_hidden_write(self):
        plan = self.plan(logic_groups={1: {"group_address": 21}})
        data = json.loads(json.dumps(plan.as_dict()))
        restored = plan_from_dict(data)
        self.assertEqual(restored.as_dict(), data)
        result = self.editor.apply(self.pp, restored)
        self.assertTrue(result["verified"])
        self.assertFalse(result["saved"])
        with self.assertRaisesRegex(PPEditError, "changed since"):
            self.editor.apply(self.pp, restored)
        for mutate in (lambda d: d["changes"].pop("LightLevelOutput"),
                       lambda d: d["changes"]["LightLevelOutput"].__setitem__(0, 99),
                       lambda d: d["derived"].clear(),
                       lambda d: d.__setitem__("recovery_modal_opened", True),
                       lambda d: d["options"]["logic_groups"]["1"].__setitem__("group_address", 22)):
            self.pp = session()
            damaged = deepcopy(data)
            mutate(damaged)
            with self.subTest(plan=damaged), self.assertRaisesRegex(PPEditError, "canonical"):
                self.editor.apply(self.pp, plan_from_dict(damaged))
            self.assertEqual(self.pp.calls, [])
        self.pp.firmware = "1.1.00"
        with self.assertRaisesRegex(PPEditError, "another firmware"):
            self.editor.apply(self.pp, restored)

    def test_plan_json_shape_and_no_hidden_noop_modal(self):
        data = self.plan().as_dict()
        self.assertEqual(data["changes"], {})
        self.assertFalse(data["recovery_modal_opened"])
        for key, value in (("saved", True), ("unknown", 1), ("options", {})):
            bad = deepcopy(data)
            bad[key] = value
            with self.assertRaises(PPEditError):
                plan_from_dict(bad)
        data["expected"]["LogicFunction"][0] = False
        with self.assertRaisesRegex(PPEditError, "integer arrays"):
            plan_from_dict(data)

    def test_uncertain_write_restores_all_attempted_fields(self):
        plan = self.plan(logic_groups={1: {"group_address": 21}})
        original = self.pp.values()
        self.pp.failure = "LightLevelOutput"
        with self.assertRaises(PPApplyError):
            self.editor.apply(self.pp, plan)
        self.assertEqual(self.pp.values(), original)
        self.assertNotIn("SAVE", [name for name, _ in self.pp.calls])
        self.assertEqual(set(plan.expected), set(LAYOUTS))
        self.assertEqual(plan.format, FORMAT)


if __name__ == "__main__":
    unittest.main()
