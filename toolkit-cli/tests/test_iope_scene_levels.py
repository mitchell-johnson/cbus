"""IOPE retained scene levels: exact projection, cascades and transaction guards."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from cbus_toolkit.iope_scene_levels import (
    FORMAT, LAYOUTS, WRITABLE, IopeSceneLevels, plan_from_dict)
from cbus_toolkit.iope_settings import PROFILES
from cbus_toolkit.memory import MemoryImage
from cbus_toolkit.pp_editor import PPApplyError, PPEditError
from cbus_toolkit.unitspec import ParameterSpec
from test_iope_scene_selectors import CACHE, DEFAULTS, fixture, session


class SceneLevelsTest(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.editor = IopeSceneLevels(self.spec)
        self.current = self.spec.defaults()
        self.identity = ("IOPE2R2", "1.2.00", "5752PP/2R")

    def plan(self, **options):
        return self.editor.plan(self.current, identity=self.identity, group_cache=CACHE,
                                scene=2, command=3, **options)

    def test_profiles_all_rows_and_full_memory_preservation(self):
        for unit_type in PROFILES:
            spec = fixture(unit_type); editor = IopeSceneLevels(spec)
            for scene in range(1, 5):
                for command in range(1, 9):
                    with self.subTest(unit_type=unit_type, scene=scene, command=command):
                        p = editor.plan(spec.defaults(), identity=(unit_type, "1.2.00", None),
                                        scene=scene, command=command, raw_level=129, group_cache=CACHE)
                        index = (scene - 1) * 16 + (command - 1) * 2 + 1
                        expected = list(DEFAULTS["SceneTable"]); expected[index] = 129
                        self.assertEqual(p.changes["SceneTable"], tuple(expected))
                        self.assertEqual(set(p.changes), WRITABLE)
                        before = editor.codec.encode_many(p.expected).apply(MemoryImage.from_bytes(bytes([0xA5]) * 256))
                        after = editor.codec.encode_many(p.changes).apply(before)
                        for address in range(256):
                            self.assertEqual(after.byte(address), 129 if address == 0xB2 + index else before.byte(address))
                        self.assertFalse(p.details["whole_dialog_save"])
                        self.assertFalse(p.details["scene_content_repacked"])
                        self.assertTrue(p.details["stable_table_projection"])
                        self.assertEqual(p.details["command_identity"], {"application": 56,
                            "group": (scene - 1) * 8 + command, "scene": scene, "command": command})

    def test_raw_noncanonical_levels_remain_exact_and_noop(self):
        for raw in (0, 1, 127, 128, 129, 254, 255):
            current = deepcopy(self.current); current["SceneTable"] = list(DEFAULTS["SceneTable"]); current["SceneTable"][19] = 1
            p = self.editor.plan(current, identity=self.identity, scene=2, command=3,
                                 raw_level=raw, group_cache=CACHE)
            table = p.changes.get("SceneTable", p.expected["SceneTable"])
            self.assertEqual(table[21], raw); self.assertEqual(table[19], 1)
        self.assertEqual(dict(self.plan(raw_level=128).changes), {})
        s = session(); self.editor.apply(s, self.plan(raw_level=128))
        self.assertFalse(any(call[0] in ("set", "save") for call in s.calls))

    def test_percent_original_conversion_and_sync_hidden_writes(self):
        # Independent Toolkit rule: truncation of percent * 255 / 100.
        for percent in range(101):
            p = self.plan(percent=percent)
            table = p.changes.get("SceneTable", p.expected["SceneTable"])
            self.assertEqual(table[21], 128 if percent == 50 else percent * 255 // 100)
        p = self.plan(percent=40, sync_levels=True)
        table = p.changes["SceneTable"]
        self.assertEqual(table[17:32:2], (102,) * 8)
        self.assertEqual(table[:16], tuple(DEFAULTS["SceneTable"][:16]))
        self.assertEqual(table[32:], tuple(DEFAULTS["SceneTable"][32:]))
        self.assertEqual(table[::2], tuple(DEFAULTS["SceneTable"][::2]))
        self.assertEqual([w["command"] for w in p.details["level_writes"]], list(range(1, 9)))
        self.assertEqual([w["setter_calls"] for w in p.details["level_writes"]], [1, 1, 3, 1, 1, 1, 1, 1])
        self.assertEqual(p.details["control_state"], {"live_groups": False, "sync_levels": True, "use_percent": True,
            "use_percent_action_toggles_after_entry": 0, "sync_action_toggles_after_entry": 1})
        self.assertEqual(self.plan(raw_level=7).details["level_writes"][0]["setter_calls"], 2)

    def test_same_display_percent_skips_conversion_per_row(self):
        for raw in (126, 127, 128):
            current = deepcopy(self.current); current["SceneTable"] = list(DEFAULTS["SceneTable"])
            current["SceneTable"][21] = raw
            p = self.editor.plan(current, identity=self.identity, scene=2, command=3,
                                 percent=50, group_cache=CACHE)
            self.assertEqual(dict(p.changes), {})
            self.assertFalse(p.details["level_writes"][0]["callback_conversion"])
        current = deepcopy(self.current); current["SceneTable"] = list(DEFAULTS["SceneTable"])
        for c, raw in enumerate((125, 126, 127, 128, 129, 0, 254, 255)):
            current["SceneTable"][17 + c * 2] = raw
        p = self.editor.plan(current, identity=self.identity, scene=2, command=1,
                             percent=50, sync_levels=True, group_cache=CACHE)
        self.assertEqual(p.changes["SceneTable"][17:32:2], (127, 126, 127, 128, 127, 127, 127, 127))
        self.assertEqual([w["callback_conversion"] for w in p.details["level_writes"]],
                         [True, False, False, False, True, True, True, True])
        self.assertEqual(p.changes["SceneTable"][::2], tuple(DEFAULTS["SceneTable"][::2]))
        no_op = self.plan(percent=50, sync_levels=True)
        self.assertEqual(dict(no_op.changes), {})

    def test_raw_sync_preserves_other_scenes_and_all_nonlevel_bits(self):
        p = self.plan(raw_level=255, sync_levels=True)
        before = self.editor.codec.encode_many(p.expected).apply(MemoryImage.from_bytes(bytes([0xA5]) * 256))
        after = self.editor.codec.encode_many(p.changes).apply(before)
        allowed = set(range(0xC3, 0xD3, 2))
        for address in range(256):
            self.assertEqual(after.byte(address), 255 if address in allowed else before.byte(address))

    def test_exact_control_types_boundaries_and_one_level(self):
        for args in ({}, {"raw_level": 4, "percent": 5}, {"raw_level": True},
                     {"raw_level": -1}, {"raw_level": 256}, {"percent": True},
                     {"percent": -1}, {"percent": 101}, {"percent": 50.0},
                     {"raw_level": 3, "sync_levels": 1}, {"raw_level": 3, "sync_levels": "false"}):
            with self.subTest(args=args), self.assertRaises(PPEditError): self.plan(**args)
        for scene, command in ((True, 1), (0, 1), (5, 1), (1, True), (1, 0), (1, 9)):
            with self.assertRaises(PPEditError):
                self.editor.plan(self.current, identity=self.identity, scene=scene, command=command,
                                 raw_level=3, group_cache=CACHE)

    def test_graph_admission_and_positive_metadata(self):
        mutations = [("SceneTriggerGroup", [255]), ("Application", [202, 57]),
                     ("SceneIndex", [0, 1, 2, 2]), ("SceneTablePointer", [157, 194, 210, 226]),
                     ("SceneTablePointer", [178, 180, 182, 184]), ("ActionSelector", [10, 11, 12, 255]),
                     ("ActionSelectorAllOff", [10, 21, 22, 23])]
        for key, value in mutations:
            current = deepcopy(self.current); current[key] = value
            with self.subTest(key=key), self.assertRaises(PPEditError):
                self.editor.plan(current, identity=self.identity, scene=2, command=3, raw_level=4, group_cache=CACHE)
        for group in (255, 33, 1):
            current = deepcopy(self.current); current["SceneTable"] = list(DEFAULTS["SceneTable"]); current["SceneTable"][2] = group
            with self.assertRaises(PPEditError):
                self.editor.plan(current, identity=self.identity, scene=2, command=3, raw_level=4, group_cache=CACHE)
        for key in ("applications", "action_selectors"):
            cache = deepcopy(CACHE); cache[key] = []
            with self.assertRaises(PPEditError):
                self.editor.plan(self.current, identity=self.identity, scene=2, command=3, raw_level=4, group_cache=cache)
        cache = deepcopy(CACHE); cache["applications"][0]["groups"].remove(32)
        with self.assertRaises(PPEditError):
            self.editor.plan(self.current, identity=self.identity, scene=2, command=3, raw_level=4, group_cache=cache)

    def test_canonical_roundtrip_apply_and_stale_each_dependency(self):
        p = self.plan(raw_level=7, sync_levels=True)
        restored = plan_from_dict(json.loads(json.dumps(p.as_dict())))
        self.assertEqual(restored.format, FORMAT)
        result = self.editor.apply(session(), restored)
        self.assertTrue(result["verified"]); self.assertFalse(result["saved"])
        self.assertEqual(result["changes"]["SceneTable"][17:32:2], [7] * 8)
        for key in LAYOUTS:
            s = session(); changed = list(DEFAULTS[key]); changed[0] ^= 1
            s.current[key] = " ".join(map(str, changed))
            with self.subTest(key=key), self.assertRaises(PPEditError): self.editor.apply(s, p)
            self.assertFalse(any(call[0] == "set" for call in s.calls))

    def test_tampered_canonical_data_refused_before_write(self):
        p = self.plan(raw_level=7, sync_levels=True)
        def changed_table(d): d["changes"]["SceneTable"][17] = 128
        mutations = [changed_table, lambda d: d["changes"].update(ActionSelector=[10, 30, 12, 13]),
                     lambda d: d["source"].update(exe_sha256="bad"),
                     lambda d: d["initialization"].update(live_groups=True),
                     lambda d: d["initialization"].update(live_groups=0),
                     lambda d: d["control_state"].update(sync_levels=False),
                     lambda d: d["level_writes"].pop(),
                     lambda d: d["command_identity"].update(group=99),
                     lambda d: d["options"].update(extra=1),
                     lambda d: d.update(scene_content_repacked=True)]
        for mutate in mutations:
            d = deepcopy(p.as_dict()); mutate(d); s = session()
            with self.subTest(document=d), self.assertRaises(PPEditError):
                self.editor.apply(s, plan_from_dict(d))
            self.assertFalse(any(call[0] == "set" for call in s.calls))
        for mutate in (lambda d: d.update(saved=True), lambda d: d.update(extra=1),
                       lambda d: d["expected"]["SceneTable"].__setitem__(0, True)):
            d = deepcopy(p.as_dict()); mutate(d)
            with self.assertRaises(PPEditError): plan_from_dict(d)
        with self.assertRaises(PPEditError): self.editor.apply(session(), replace(p, changes={}))

    def test_staging_failure_rolls_back_and_never_saves(self):
        s = session(); s.failure = "SceneTable"
        with self.assertRaises(PPApplyError): self.editor.apply(s, self.plan(raw_level=0, sync_levels=True))
        self.assertEqual(s.values(), session().values())
        self.assertFalse(any(call[0] == "save" for call in s.calls))

    def test_schema_profile_and_missing_identity(self):
        for identity in (None, ("IOPE2R2", "1.3.00", None), ("IOPE2R2", "1.2.00", "wrong"),
                         ("IOPE1R1", "1.2.00", None)):
            with self.assertRaises(PPEditError):
                self.editor.plan(self.current, identity=identity, scene=2, command=3, raw_level=4, group_cache=CACHE)
        for firmware in ("0.9.99", "1.3.00", None):
            s = session(); s.firmware = firmware
            with self.assertRaises(PPEditError): self.editor.apply(s, self.plan(raw_level=4))
        malformed = fixture(); fields = dict(malformed.parameters["SceneTable"].fields); fields["Address"] = "179"
        malformed.parameters["SceneTable"] = ParameterSpec("SceneTable", "int", "synthetic.xml", fields)
        with self.assertRaises(PPEditError): IopeSceneLevels(malformed)

    def test_show_retained_rows_without_claiming_metadata(self):
        shown = self.editor.show(self.current)
        self.assertEqual(shown["scenes"][1]["commands"][2], {"command": 3, "group": 11, "raw_level": 128, "percent": 50})
        self.assertFalse(shown["group_objects_resolved"])


if __name__ == "__main__":
    unittest.main()
