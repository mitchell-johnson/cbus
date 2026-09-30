"""Bounded IOPE output control rules and transaction/preservation checks."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from cbus_toolkit.iope_output_settings import (FORMAT, LAYOUTS, PROFILES,
                                             IopeOutputSettings, plan_from_dict)
from cbus_toolkit.memory import MemoryImage
from cbus_toolkit.pp_editor import PPApplyError, PPEditError
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec
from test_macros import Session

# Literal original UnitSpec geometry, independent of the module's LAYOUTS.
ROWS = {
    "MinDimmingLevel": (0x78, 4, 8, 0, "0 0 51 25"),
    "MaxDimmingLevel": (0x7C, 2, 8, 0, "102 255"),
    "RestrikeChannel": (0x70, 4, 1, 6, "0 0 1 1"),
    "RestrikeDelay": (0x6F, 1, 8, 0, "60"),
    "LogicGA13Associations": (0x70, 4, 1, 0, "1 0 1 0"),
    "LogicFunction": (0x70, 4, 1, 7, "1 1 0 0"),
    "UnitAddress": (0x20, 1, 8, 0, "37"),
}


def fixture(unit_type="IOPE2C4"):
    params = {}
    for name, (address, count, bits, bit, default) in ROWS.items():
        fields = {"Name": name, "Type": "int", "Address": str(address), "ArraySize": str(count),
                  "BitSize": str(bits), "BitAddress": str(bit), "ArraySkip": "0", "DefaultValue": default,
                  "MinValue": "0", "MaxValue": str((1 << bits) - 1)}
        params[name] = ParameterSpec(name, "int", "synthetic-iope-output.xml", fields)
    return UnitSpec(unit_type + ".xml", {"Type": unit_type}, ("synthetic-iope-output.xml",), params)


def session(unit_type="IOPE2C4", firmware="1.2.00"):
    pp = Session(fixture(unit_type))
    pp.firmware, pp.catalog_number = firmware, PROFILES[unit_type].catalog_number
    return pp


class IopeOutputSettingsTest(unittest.TestCase):
    def setUp(self):
        self.pp = session()
        self.editor = IopeOutputSettings(self.pp.spec)
        self.identity = (self.pp.unit_type, self.pp.firmware, self.pp.catalog_number)

    def plan(self, **options):
        return self.editor.plan(self.pp.values(), identity=self.identity, **options)

    def test_profile_identity_and_layout_gates(self):
        for unit_type in PROFILES:
            pp = session(unit_type)
            editor = IopeOutputSettings(pp.spec)
            for firmware in ("1.0.00", "1.1.00", "1.2.99"):
                editor.plan(pp.values(), identity=(unit_type, firmware, pp.catalog_number), channels={1: {"min_percent": 50}})
        for firmware in (None, "1.2", "1.3.00", "0.9.99", "9.0.00"):
            with self.subTest(firmware=firmware), self.assertRaises(PPEditError):
                self.editor.plan(self.pp.values(), identity=("IOPE2C4", firmware, None))
        with self.assertRaisesRegex(PPEditError, "explicit"):
            self.editor.plan(self.pp.values(), channels={1: {"min_percent": 50}})
        with self.assertRaisesRegex(PPEditError, "Catalogue"):
            self.editor.plan(self.pp.values(), identity=("IOPE2C4", "1.2.00", "5752PP/1R"))
        with self.assertRaisesRegex(PPEditError, "matching"):
            IopeOutputSettings(fixture("IOPE1R1"), "IOPE2C4")
        wrong = fixture()
        fields = dict(wrong.get("MaxDimmingLevel").fields)
        fields["Address"] = "128"
        wrong.parameters["MaxDimmingLevel"] = replace(wrong.get("MaxDimmingLevel"), fields=fields)
        with self.assertRaisesRegex(PPEditError, "layout"):
            IopeOutputSettings(wrong)

    def test_relay_threshold_preserves_inactive_slots(self):
        for unit_type, count in (("IOPE1R1", 1), ("IOPE2R2", 2), ("IOPE2C4", 4)):
            pp = session(unit_type)
            editor = IopeOutputSettings(pp.spec)
            plan = editor.plan(pp.values(), identity=(unit_type, pp.firmware, pp.catalog_number),
                               channels={1: {"min_percent": 50}})
            self.assertEqual(dict(plan.changes), {"MinDimmingLevel": (127, 0, 51, 25)})
            self.assertEqual(len(editor.show(pp.values())["channels"]), count)
            with self.assertRaises(PPEditError):
                editor.plan(pp.values(), identity=(unit_type, pp.firmware, pp.catalog_number),
                            channels={count + 1: {"min_percent": 50}})
            with self.assertRaisesRegex(PPEditError, "no maximum"):
                editor.plan(pp.values(), identity=(unit_type, pp.firmware, pp.catalog_number),
                            channels={1: {"max_percent": 50}})

    def test_dimmer_minimum_crossing_updates_paired_maximum(self):
        plan = self.plan(channels={3: {"min_percent": 60}})
        self.assertEqual(dict(plan.changes), {"MinDimmingLevel": (0, 0, 153, 25),
                                             "MaxDimmingLevel": (155, 255)})
        self.assertEqual(plan.details["derived"], ["MaxDimmingLevel[0]:minimum-slider-cascade"])
        # The second maximum belongs to channel 4, never relay channel 2.
        plan = self.plan(channels={4: {"max_percent": 5}})
        self.assertEqual(dict(plan.changes), {"MinDimmingLevel": (0, 0, 51, 10),
                                             "MaxDimmingLevel": (102, 12)})
        self.assertEqual(plan.details["derived"], ["MinDimmingLevel[3]:maximum-slider-cascade"])

    def test_uncrossed_pair_preserves_noncanonical_raw_level(self):
        # Raw 52 displays 20%, but re-encoding 20% gives 51. An uncrossed
        # maximum change must not accidentally quantize its neighbor.
        self.pp.set("MinDimmingLevel", "0 0 52 25")
        plan = self.plan(channels={3: {"max_percent": 90}})
        self.assertEqual(dict(plan.changes), {"MaxDimmingLevel": (229, 255)})
        self.assertEqual(plan.details["derived"], [])

    def test_minimum_then_maximum_and_saturated_edges(self):
        plan = self.plan(channels={3: {"min_percent": 80, "max_percent": 20}})
        self.assertEqual(plan.changes["MinDimmingLevel"][2], 48)
        self.assertEqual(plan.changes["MaxDimmingLevel"][0], 51)
        self.assertEqual(len(plan.details["derived"]), 2)
        plan = self.plan(channels={3: {"max_percent": 0}})
        self.assertEqual(plan.changes["MinDimmingLevel"][2], 0)
        self.assertEqual(plan.changes["MaxDimmingLevel"][0], 0)
        plan = self.plan(channels={3: {"min_percent": 100}})
        self.assertEqual(plan.changes["MinDimmingLevel"][2], 255)
        self.assertEqual(plan.changes["MaxDimmingLevel"][0], 255)

    def test_restrike_delay_admission_and_stored_hidden_bits(self):
        # Stored dimmer bits never enable the delay control, and must stay.
        self.assertFalse(self.editor.show(self.pp.values())["restrike_delay_editable"])
        with self.assertRaisesRegex(PPEditError, "until a relay"):
            self.plan(restrike_delay=254)
        with self.assertRaisesRegex(PPEditError, "only on relay"):
            self.plan(channels={3: {"restrike": False}})
        plan = self.plan(channels={2: {"restrike": True}}, restrike_delay=254)
        self.assertEqual(dict(plan.changes), {"RestrikeChannel": (0, 1, 1, 1), "RestrikeDelay": (254,)})
        self.editor.apply(self.pp, plan)
        self.assertEqual(self.editor.show(self.pp.values())["restrike_delay_seconds"], 2540)
        with self.assertRaisesRegex(PPEditError, "until a relay"):
            self.plan(channels={2: {"restrike": False}}, restrike_delay=1)
        pp = session("IOPE1R1")
        pp.set("RestrikeChannel", "0 1 1 1")
        with self.assertRaisesRegex(PPEditError, "until a relay"):
            IopeOutputSettings(pp.spec).plan(pp.values(), identity=(pp.unit_type, pp.firmware, None), restrike_delay=1)

    def test_domains_and_unknown_controls_fail_before_mutation(self):
        before = self.pp.values()
        for options in ({"channels": {True: {"min_percent": 50}}}, {"channels": {0: {"min_percent": 50}}},
                        {"channels": {1: {"min_percent": -1}}}, {"channels": {1: {"min_percent": 101}}},
                        {"channels": {1: {"min_percent": True}}}, {"channels": {1: {"restrike": 1}}},
                        {"channels": {1: {"min_level": 1}}}, {"channels": {1: {"logic_function": "or"}}},
                        {"channels": []}, {"channels": {1: {}}}, {"channels": {1: None}},
                        {"channels": {1: {"restrike": True}}, "restrike_delay": 0},
                        {"channels": {1: {"restrike": True}}, "restrike_delay": 255}):
            with self.subTest(options=options), self.assertRaises(PPEditError):
                self.plan(**options)
        self.assertEqual(self.pp.values(), before)
        self.assertEqual(self.pp.calls, [])

    def test_shared_memory_bits_and_inactive_slots_are_preserved(self):
        for unit_type in PROFILES:
            pp = session(unit_type)
            editor = IopeOutputSettings(pp.spec)
            image = editor.codec.encode_many({name: list(map(int, value.split())) for name, value in pp.values().items()}).apply(
                MemoryImage.from_bytes(bytes([0x35]) * 256))
            plan = editor.plan(pp.values(), identity=(unit_type, pp.firmware, pp.catalog_number), channels={1: {"restrike": True}})
            after = editor.codec.encode_many(plan.changes).apply(image)
            self.assertEqual(after.byte(0x70), image.byte(0x70) | 0x40)
            for address in range(256):
                if address != 0x70:
                    self.assertEqual(after.byte(address), image.byte(address))
            self.assertEqual(after.byte(0x70) & 0xBF, image.byte(0x70) & 0xBF)

    def test_saved_plan_replay_stale_profile_and_forgery_refusals(self):
        plan = self.plan(channels={3: {"min_percent": 60}})
        document = json.loads(json.dumps(plan.as_dict()))
        restored = plan_from_dict(document)
        self.assertEqual(restored.as_dict(), document)
        result = self.editor.apply(self.pp, restored)
        self.assertTrue(result["verified"])
        self.assertFalse(result["saved"])
        self.assertEqual(self.pp.values()["UnitAddress"], "37")
        with self.assertRaisesRegex(PPEditError, "changed since"):
            self.editor.apply(self.pp, restored)
        self.pp = session()
        for mutate in (
            lambda d: d["changes"].pop("MaxDimmingLevel"),
            lambda d: d["changes"]["MinDimmingLevel"].__setitem__(0, 7),
            lambda d: d["derived"].clear(),
            lambda d: d["options"]["channels"]["3"].__setitem__("min_percent", 20),
            lambda d: d.__setitem__("whole_dialog_save", True),
        ):
            damaged = deepcopy(document)
            mutate(damaged)
            with self.subTest(document=damaged), self.assertRaisesRegex(PPEditError, "canonical"):
                self.editor.apply(self.pp, plan_from_dict(damaged))
        self.assertEqual(self.pp.calls, [])
        self.pp.firmware = "1.1.00"
        with self.assertRaisesRegex(PPEditError, "another firmware"):
            self.editor.apply(self.pp, restored)

    def test_saved_plan_json_shape_is_strict(self):
        data = self.plan(channels={1: {"min_percent": 25}}).as_dict()
        for key, value in (("saved", True), ("extra", 1), ("options", {})):
            altered = deepcopy(data)
            altered[key] = value
            with self.assertRaises(PPEditError):
                plan_from_dict(altered)
        data["expected"]["RestrikeChannel"][0] = False
        with self.assertRaisesRegex(PPEditError, "integer arrays"):
            plan_from_dict(data)

    def test_uncertain_write_restores_attempted_fields_without_save(self):
        pp = session()
        editor = IopeOutputSettings(pp.spec)
        plan = editor.plan(pp.values(), identity=(pp.unit_type, pp.firmware, pp.catalog_number),
                           channels={3: {"min_percent": 60}})
        original = pp.values()
        pp.failure = "MaxDimmingLevel"
        with self.assertRaises(PPApplyError):
            editor.apply(pp, plan)
        self.assertEqual(pp.values(), original)
        self.assertNotIn("SAVE", [name for name, _ in pp.calls])
        self.assertEqual(set(plan.expected), set(LAYOUTS))
        self.assertEqual(plan.format, FORMAT)


if __name__ == "__main__":
    unittest.main()
