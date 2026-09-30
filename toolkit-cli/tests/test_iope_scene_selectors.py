"""Independent IOPE scene selector component vectors and preservation guards."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from cbus_toolkit.iope_scene_selectors import (
    CACHE_FORMAT, FORMAT, LAYOUTS, WRITABLE, IopeSceneSelectors, plan_from_dict)
from cbus_toolkit.iope_settings import PROFILES
from cbus_toolkit.memory import MemoryImage
from cbus_toolkit.pp_editor import PPApplyError, PPEditError
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec
from test_macros import Session

CACHE = {"format": CACHE_FORMAT, "source": "synthetic complete same-network LevelManager inventory",
         "applications": [{"address": 56, "groups": list(range(1, 33))}, {"address": 202, "groups": [7]}],
         "action_selectors": [{"application": 202, "group": 7, "addresses": [10, 11, 12, 13, 20, 21, 22, 23, 30]}]}
DEFAULTS = {"Application": [56, 57], "SceneTriggerGroup": [7], "SceneIndex": [0, 1, 2, 3],
            "SceneCommandRampRate": [0, 1, 2, 3], "ActionSelector": [10, 11, 12, 13],
            "ActionSelectorAllOff": [20, 21, 22, 23], "SceneTablePointer": [178, 194, 210, 226],
            "SceneTable": [x for group in range(1, 33) for x in (group, 128)]}


def fixture(unit_type="IOPE2R2"):
    parameters = {}
    for name, (kind, address, size, bits, bit, skip) in LAYOUTS.items():
        fields = {"Name": name, "Type": kind, "Address": str(address), "ArraySize": str(size),
                  "BitAddress": str(bit), "BitSize": str(bits), "ArraySkip": str(skip),
                  "DefaultValue": " ".join(map(str, DEFAULTS[name])),
                  "MinValue": "0", "MaxValue": str((1 << bits) - 1)}
        parameters[name] = ParameterSpec(name, kind, "synthetic.xml", fields)
    for name, address, value in (("Unrelated", 0x70, 71), ("SensorCommand", 0x80, 0x81),
                                 ("JoinSentinel", 0x63, 22)):
        parameters[name] = ParameterSpec(name, "int", "synthetic.xml", {
            "Name": name, "Type": "int", "Address": str(address), "DefaultValue": str(value)})
    return UnitSpec(unit_type + ".xml", {"Type": unit_type}, ("synthetic.xml",), parameters)


def session(unit_type="IOPE2R2"):
    result = Session(fixture(unit_type))
    result.firmware = "1.2.00"
    result.catalog_number = PROFILES[unit_type].catalog_number
    return result


class SceneSelectorsTest(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.editor = IopeSceneSelectors(self.spec)
        self.current = self.spec.defaults()
        self.identity = ("IOPE2R2", "1.2.00", "5752PP/2R")

    def plan(self, **options):
        return self.editor.plan(self.current, identity=self.identity, group_cache=CACHE, **options)

    def test_all_profiles_slots_and_owned_byte_only(self):
        for unit_type in PROFILES:
            editor = IopeSceneSelectors(fixture(unit_type))
            for scene in range(1, 5):
                for option, field, base in (("normal_selector", "ActionSelector", 0xA6),
                                            ("all_off_selector", "ActionSelectorAllOff", 0xAA)):
                    with self.subTest(unit_type=unit_type, scene=scene, field=field):
                        plan = editor.plan(fixture(unit_type).defaults(), identity=(unit_type, "1.2.00", None),
                                           scene=scene, group_cache=CACHE, **{option: 30})
                        self.assertEqual(set(plan.changes), {field})
                        expected = list(DEFAULTS[field]); expected[scene - 1] = 30
                        self.assertEqual(plan.changes[field], tuple(expected))
                        before = editor.codec.encode_many(plan.expected).apply(MemoryImage.from_bytes(bytes([0xA5]) * 256))
                        after = editor.codec.encode_many(plan.changes).apply(before)
                        for a in range(256):
                            self.assertEqual(after.byte(a), 30 if a == base + scene - 1 else before.byte(a))
                        self.assertLessEqual(set(plan.changes), WRITABLE)
                        self.assertFalse(plan.details["whole_dialog_save"])
                        self.assertFalse(plan.details["scene_content_repacked"])

    def test_same_selector_noop_and_native_collision_filter(self):
        self.assertEqual(dict(self.plan(scene=2, normal_selector=11).changes), {})
        for action in (10, 12, 13, 20, 21, 22, 23):
            with self.subTest(action=action), self.assertRaisesRegex(PPEditError, "opposite selector or another scene"):
                self.plan(scene=2, normal_selector=action)

    def test_unresolved_external_and_noncanonical_graphs_fail(self):
        cases = (("SceneTriggerGroup", [255]), ("SceneIndex", [1, 0, 2, 3]),
                 ("SceneTablePointer", [157, 194, 210, 226]),
                 ("SceneTablePointer", [178, 180, 182, 184]),
                 ("ActionSelector", [10, 11, 12, 255]),
                 ("ActionSelectorAllOff", [10, 21, 22, 23]), ("Application", [202, 57]))
        for field, values in cases:
            with self.subTest(field=field, values=values), self.assertRaises(PPEditError):
                current = deepcopy(self.current); current[field] = values
                self.editor.plan(current, identity=self.identity, scene=2, normal_selector=30, group_cache=CACHE)
        for group in (255, 33):
            current = deepcopy(self.current); current["SceneTable"] = list(DEFAULTS["SceneTable"]); current["SceneTable"][0] = group
            with self.assertRaises(PPEditError):
                self.editor.plan(current, identity=self.identity, scene=2, normal_selector=30, group_cache=CACHE)

    def test_duplicate_command_groups_collapse_during_native_load(self):
        for scene in range(4):
            current = deepcopy(self.current); table = list(DEFAULTS["SceneTable"])
            table[scene * 16 + 2] = table[scene * 16]
            current["SceneTable"] = table
            with self.subTest(scene=scene), self.assertRaisesRegex(PPEditError, "collapses duplicates"):
                self.editor.plan(current, identity=self.identity, scene=2, normal_selector=30, group_cache=CACHE)

    def test_cache_complete_shape_and_missing_objects(self):
        mutations = [lambda c: c["applications"].pop(),
                     lambda c: c["applications"][0]["groups"].remove(1),
                     lambda c: c["action_selectors"][0]["addresses"].remove(10),
                     lambda c: c["action_selectors"][0]["addresses"].remove(30),
                     lambda c: c["action_selectors"][0].update(group=8),
                     lambda c: c["action_selectors"][0]["addresses"].append(30),
                     lambda c: c["action_selectors"][0]["addresses"].append(True),
                     lambda c: c.update(extra=True)]
        for mutate in mutations:
            cache = deepcopy(CACHE); mutate(cache)
            with self.subTest(cache=cache), self.assertRaises(PPEditError):
                self.editor.plan(self.current, identity=self.identity, scene=2, normal_selector=30, group_cache=cache)

    def test_exact_option_types_and_one_selection(self):
        for options in ({"scene": True, "normal_selector": 30}, {"scene": 0, "normal_selector": 30},
                        {"scene": 5, "normal_selector": 30}, {"scene": 2, "normal_selector": True},
                        {"scene": 2, "normal_selector": 255}, {"scene": 2},
                        {"scene": 2, "normal_selector": 30, "all_off_selector": 30}):
            with self.subTest(options=options), self.assertRaises(PPEditError):
                self.plan(**options)

    def test_canonical_json_apply_stale_dependency_and_forged_changes(self):
        s = session(); plan = self.plan(scene=2, normal_selector=30)
        restored = plan_from_dict(json.loads(json.dumps(plan.as_dict())))
        result = self.editor.apply(s, restored)
        self.assertTrue(result["verified"]); self.assertFalse(result["saved"])
        self.assertEqual(s.current["ActionSelector"], "10 30 12 13")
        for dependency in LAYOUTS:
            s = session(); values = list(DEFAULTS[dependency]); values[0] = values[0] ^ 1
            s.current[dependency] = " ".join(map(str, values))
            with self.subTest(dependency=dependency), self.assertRaises(PPEditError):
                self.editor.apply(s, plan)
            self.assertFalse(any(c[0] == "set" for c in s.calls))
        altered = replace(plan, changes={"ActionSelectorAllOff": (20, 30, 22, 23)})
        with self.assertRaisesRegex(PPEditError, "canonical"):
            self.editor.apply(session(), altered)
        d = plan.as_dict(); d["changes"]["ActionSelector"][1] = True
        with self.assertRaises(PPEditError): plan_from_dict(d)

    def test_rollback_and_no_save(self):
        s = session(); s.failure = "ActionSelector"
        with self.assertRaises(PPApplyError):
            self.editor.apply(s, self.plan(scene=2, normal_selector=30))
        self.assertEqual(s.values(), session().values())
        self.assertFalse(any(c[0] == "save" for c in s.calls))

    def test_schema_and_identity_refuse_before_write(self):
        s = session(); s.firmware = "1.3.00"
        with self.assertRaises(PPEditError): self.editor.apply(s, self.plan(scene=2, normal_selector=30))
        self.assertFalse(any(c[0] == "set" for c in s.calls))
        malformed = fixture(); fields = dict(malformed.parameters["ActionSelector"].fields)
        fields["Address"] = str(0xA7)
        malformed.parameters["ActionSelector"] = ParameterSpec("ActionSelector", "int", "synthetic.xml", fields)
        with self.assertRaises(PPEditError): IopeSceneSelectors(malformed)


if __name__ == "__main__":
    unittest.main()
