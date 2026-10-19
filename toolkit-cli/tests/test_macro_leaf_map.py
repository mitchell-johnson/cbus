"""Macro-leaf map: roster, preset/micro binding, determinism and explicit gaps."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from cbus_toolkit import macros
from research import map_macro_leaves as leaf_map


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "docs" / "toolkit-macro-leaf-map.json"


def committed() -> dict:
    return json.loads(MAP_PATH.read_text(encoding="utf-8"))


def surface_leaves() -> list[tuple[str, str]]:
    surface = json.loads((ROOT / "docs/toolkit-surface.json").read_text(encoding="utf-8"))
    return leaf_map.leaf_roster(surface["macro_reference"]["tree"])


class MacroLeafMapTests(unittest.TestCase):
    def test_all_179_leaves_are_preserved_in_surface_order(self):
        document = committed()
        ids = [row["leaf_id"] for row in document["leaves"]]
        self.assertEqual(len(ids), 179)
        self.assertEqual(ids, [topic_id for topic_id, _ in surface_leaves()])
        counts = document["counts"]
        self.assertEqual(counts["leaves"], 179)
        self.assertEqual(
            counts["mapped_preset"] + counts["mapped_custom"]
            + counts["mapped_micro_function"] + counts["pending"],
            179,
        )

    def test_every_leaf_resolves_or_names_its_gap(self):
        for row in committed()["leaves"]:
            with self.subTest(row["leaf_id"]):
                if row["status"] == "mapped":
                    self.assertEqual(row["reasons"], [])
                    if row["kind"] == "preset":
                        for name in row["presets"]:
                            self.assertIn(name, macros.PRESETS)
                    elif row["kind"] == "micro_function":
                        self.assertIn(row["micro_function"], macros.MICRO_FUNCTIONS)
                    else:
                        self.assertEqual(row["kind"], "custom")
                else:
                    self.assertEqual(row["status"], "pending")
                    self.assertTrue(row["reasons"])
                    for reason in row["reasons"]:
                        self.assertEqual(reason["detail"], leaf_map.REASONS[reason["code"]])

    def test_wired_templates_cover_all_presets(self):
        document = committed()
        covered = {
            name
            for row in document["leaves"]
            if row["kind"] == "preset"
            for name in row["presets"]
        }
        self.assertEqual(covered, set(macros.PRESETS))
        custom = [row for row in document["leaves"] if row["kind"] == "custom"]
        self.assertEqual([row["leaf_id"] for row in custom], ["help:975.htm"])

    def test_wired_micro_leaves_cover_the_domain(self):
        document = committed()
        covered = {
            row["micro_function"]
            for row in document["leaves"]
            if row["kind"] == "micro_function"
        }
        self.assertEqual(covered, set(macros.MICRO_FUNCTIONS))

    def test_p001_narrow_subset_pins_wired_leaves_with_open_gaps(self):
        # P0.01 census increment: pin a small verifiable wired subset to live
        # implementation; the census stays open with 145 pending leaves.
        by_id = {row["leaf_id"]: row for row in committed()["leaves"]}
        expected_presets = {
            "help:965.htm": ["bellpress"],
            "help:961.htm": ["dimmer", "dimmer_memory"],
            "help:958.htm": ["on"],
            "help:959.htm": ["off"],
        }
        for leaf_id, names in expected_presets.items():
            with self.subTest(leaf_id):
                row = by_id[leaf_id]
                self.assertEqual(row["status"], "mapped")
                self.assertEqual(row["kind"], "preset")
                self.assertEqual(row["presets"], names)
                for name in names:
                    self.assertIn(name, macros.PRESETS)
                    self.assertEqual(f"help:{macros.PRESETS[name].help_topic}", leaf_id)
        with self.subTest("help:975.htm"):
            row = by_id["help:975.htm"]
            self.assertEqual((row["status"], row["kind"]), ("mapped", "custom"))
        for leaf_id, code in (
            ("help:977.htm", "idle"),
            ("help:989.htm", "toggle"),
            ("help:990.htm", "on"),
        ):
            with self.subTest(leaf_id):
                row = by_id[leaf_id]
                self.assertEqual((row["status"], row["kind"]), ("mapped", "micro_function"))
                self.assertEqual(row["micro_function"], code)
                self.assertIn(code, macros.MICRO_FUNCTIONS)
        counts = committed()["counts"]
        self.assertEqual(counts["pending"], 145)
        self.assertEqual(counts["mapped_preset"] + counts["mapped_custom"]
                         + counts["mapped_micro_function"], 34)

    def test_p001_shutter_subset_pins_explicit_gaps(self):
        # P0.01 census increment: the 6 shutter leaves stay outside the
        # admitted classic key-macro scope; none maps to live code.
        by_id = {row["leaf_id"]: row for row in committed()["leaves"]}
        expected_titles = {
            "help:5133.htm": "Shutter toggle (wired)",
            "help:5134.htm": "Shutter close toggle (wired)",
            "help:5135.htm": "Shutter open toggle (wired)",
            "help:5136.htm": "Shutter open (wired)",
            "help:5137.htm": "Shutter close (wired)",
            "help:5138.htm": "Shutter stop (wired)",
        }
        live_topics = {f"help:{preset.help_topic}" for preset in macros.PRESETS.values()}
        for leaf_id, title in expected_titles.items():
            with self.subTest(leaf_id):
                row = by_id[leaf_id]
                self.assertEqual(row["title"], title)
                self.assertEqual((row["status"], row["kind"]), ("pending", "pending"))
                self.assertEqual(row["reasons"], [{
                    "code": "shutter",
                    "detail": leaf_map.REASONS["shutter"],
                    "subjects": [title],
                }])
                # Negative live-code binding: no preset help_topic and no
                # wired micro-function topic covers a shutter leaf.
                self.assertNotIn(leaf_id, live_topics)
                self.assertNotIn(leaf_id, leaf_map.MICRO_WIRED_TOPICS)
        counts = committed()["counts"]
        self.assertEqual(counts["pending"], 145)
        self.assertEqual(counts["mapped_preset"] + counts["mapped_custom"]
                         + counts["mapped_micro_function"], 34)
        self.assertEqual(counts["pending_reasons"]["shutter"], 6)

    def test_p001_schedule_fan_occupancy_aux_subset_pin_explicit_gaps(self):
        # P0.01 census increment: schedule-move/fan/occupancy/AUX-subset leaves
        # stay outside the admitted classic key-macro scope; none maps to live code.
        by_id = {row["leaf_id"]: row for row in committed()["leaves"]}
        expected = {
            "help:10114.htm": ("Day Move", "schedule_move"),
            "help:10115.htm": ("Night Move", "schedule_move"),
            "help:10116.htm": ("Sunset", "schedule_move"),
            "help:17328.htm": ("Any Move", "schedule_move"),
            "help:13242.htm": ("Fan Speed Cycle macro function (wired)", "fan"),
            "help:14458.htm": ("Occupancy Detector macro function", "occupancy"),
            "help:14478.htm": ("Aux On/Off macro function", "aux_subset"),
        }
        live_topics = {f"help:{preset.help_topic}" for preset in macros.PRESETS.values()}
        for leaf_id, (title, code) in expected.items():
            with self.subTest(leaf_id):
                row = by_id[leaf_id]
                self.assertEqual(row["title"], title)
                self.assertEqual((row["status"], row["kind"]), ("pending", "pending"))
                self.assertEqual(row["reasons"], [{
                    "code": code,
                    "detail": leaf_map.REASONS[code],
                    "subjects": [title],
                }])
                # Negative live-code binding: no preset help_topic and no
                # wired micro-function topic covers a small-family leaf.
                self.assertNotIn(leaf_id, live_topics)
                self.assertNotIn(leaf_id, leaf_map.MICRO_WIRED_TOPICS)
        counts = committed()["counts"]
        self.assertEqual(counts["pending"], 145)
        self.assertEqual(counts["mapped_preset"] + counts["mapped_custom"]
                         + counts["mapped_micro_function"], 34)
        self.assertEqual(counts["pending_reasons"]["schedule_move"], 4)
        self.assertEqual(counts["pending_reasons"]["fan"], 1)
        self.assertEqual(counts["pending_reasons"]["occupancy"], 1)
        self.assertEqual(counts["pending_reasons"]["aux_subset"], 1)

    def test_p001_guide_only_subset_pins_explicit_gaps(self):
        # P0.01 census increment: the 6 guide leaves describe interaction
        # rather than a selectable macro function; none maps to live code.
        by_id = {row["leaf_id"]: row for row in committed()["leaves"]}
        expected = {
            "help:937.htm": "Using the Increment macro function",
            "help:937_1.htm": "Using the Increment macro function",
            "help:931.htm": "Using the Mem Toggle Up Cycle macro function",
            "help:908.htm": "Using Scene Toggle",
            "help:933.htm": "Using the Timer macro function",
            "help:928.htm": "Toggle Dim Up Cycle user interaction",
        }
        live_topics = {f"help:{preset.help_topic}" for preset in macros.PRESETS.values()}
        for leaf_id, title in expected.items():
            with self.subTest(leaf_id):
                row = by_id[leaf_id]
                self.assertEqual(row["title"], title)
                self.assertEqual((row["status"], row["kind"]), ("pending", "pending"))
                self.assertEqual(row["reasons"], [{
                    "code": "guide_only",
                    "detail": leaf_map.REASONS["guide_only"],
                    "subjects": [title],
                }])
                # Negative live-code binding: no preset help_topic and no
                # wired micro-function topic covers a guide leaf.
                self.assertNotIn(leaf_id, live_topics)
                self.assertNotIn(leaf_id, leaf_map.MICRO_WIRED_TOPICS)
        counts = committed()["counts"]
        self.assertEqual(counts["pending"], 145)
        self.assertEqual(counts["mapped_preset"] + counts["mapped_custom"]
                         + counts["mapped_micro_function"], 34)
        self.assertEqual(counts["pending_reasons"]["guide_only"], 6)

    def test_p001_scene_widget_subset_pins_explicit_gaps(self):
        # P0.01 census increment: the 11 scene-widget leaves stay outside the
        # admitted classic key-macro scope; none maps to live code.
        by_id = {row["leaf_id"]: row for row in committed()["leaves"]}
        expected = {
            "help:11944.htm": "Scene macro function (wired)",
            "help:11946.htm": "Modify scene macro function (wired)",
            "help:14464.htm": "Scene Set macro function",
            "help:14463.htm": "Scene On/Off macro function",
            "help:14490.htm": "Scene Set micro function",
            "help:14491.htm": "Scene Toggle micro function",
            "help:14492.htm": "Scene Modify Off micro function",
            "help:14493.htm": "Scene Modify Down Key micro function",
            "help:14494.htm": "Scene Modify Up Key micro function",
            "help:14495.htm": "Scene End Ramp micro function",
            "help:14496.htm": "Scene Modify Downcycle micro function",
        }
        live_topics = {f"help:{preset.help_topic}" for preset in macros.PRESETS.values()}
        for leaf_id, title in expected.items():
            with self.subTest(leaf_id):
                row = by_id[leaf_id]
                self.assertEqual(row["title"], title)
                self.assertEqual((row["status"], row["kind"]), ("pending", "pending"))
                self.assertEqual(row["reasons"], [{
                    "code": "scene_widget",
                    "detail": leaf_map.REASONS["scene_widget"],
                    "subjects": [title],
                }])
                # Negative live-code binding: no preset help_topic and no
                # wired micro-function topic covers a scene-widget leaf.
                self.assertNotIn(leaf_id, live_topics)
                self.assertNotIn(leaf_id, leaf_map.MICRO_WIRED_TOPICS)
        counts = committed()["counts"]
        self.assertEqual(counts["pending"], 145)
        self.assertEqual(counts["mapped_preset"] + counts["mapped_custom"]
                         + counts["mapped_micro_function"], 34)
        self.assertEqual(counts["pending_reasons"]["scene_widget"], 11)

    def test_p001_bistable_subset_pins_explicit_gaps(self):
        # P0.01 census increment: the 17 bistable leaves stay outside the
        # admitted classic key-macro scope; none maps to live code.
        by_id = {row["leaf_id"]: row for row in committed()["leaves"]}
        expected = {
            "help:9890.htm": "On/Off bistable (wired)",
            "help:9891.htm": "Off/On bistable (wired)",
            "help:9892.htm": "On/Off toggle bistable (wired)",
            "help:9893.htm": "On/Off toggle timer bistable (wired)",
            "help:9894.htm": "Memory toggle bistable (wired)",
            "help:9895.htm": "Soft on/Soft off bistable (wired)",
            "help:9896.htm": "Soft on/Hard off bistable (wired)",
            "help:9897.htm": "Hard on/Soft off bistable (wired)",
            "help:14533.htm": "On/Off bistable macro function",
            "help:14534.htm": "Off/On bistable macro function",
            "help:14550.htm": "On/Off Toggle bistable macro function",
            "help:14535.htm": "On/Off Toggle Timer bistable macro function",
            "help:14536.htm": "Mem Toggle bistable macro function",
            "help:14547.htm": "Soft On/Off bistable macro function",
            "help:14548.htm": "Soft On/Hard Off bistable macro function",
            "help:14549.htm": "Hard On/Soft Off bistable macro function",
            "help:14487.htm": "Mem Toggle micro function",
        }
        live_topics = {f"help:{preset.help_topic}" for preset in macros.PRESETS.values()}
        for leaf_id, title in expected.items():
            with self.subTest(leaf_id):
                row = by_id[leaf_id]
                self.assertEqual(row["title"], title)
                self.assertEqual((row["status"], row["kind"]), ("pending", "pending"))
                self.assertEqual(row["reasons"], [{
                    "code": "bistable",
                    "detail": leaf_map.REASONS["bistable"],
                    "subjects": [title],
                }])
                # Negative live-code binding: no preset help_topic and no
                # wired micro-function topic covers a bistable leaf.
                self.assertNotIn(leaf_id, live_topics)
                self.assertNotIn(leaf_id, leaf_map.MICRO_WIRED_TOPICS)
        counts = committed()["counts"]
        self.assertEqual(counts["pending"], 145)
        self.assertEqual(counts["mapped_preset"] + counts["mapped_custom"]
                         + counts["mapped_micro_function"], 34)
        self.assertEqual(counts["pending_reasons"]["bistable"], 17)

    def test_p001_special_micro_function_subset_pins_explicit_gaps(self):
        # P0.01 census increment: the 16 scene/block/POT specialist
        # micro-function leaves stay outside the 0..15 classic domain;
        # none maps to live code.
        by_id = {row["leaf_id"]: row for row in committed()["leaves"]}
        expected = {
            "help:14482.htm": "Recall micro function",
            "help:14483.htm": "Ramp On micro function",
            "help:14484.htm": "Ramp Off micro function",
            "help:14486.htm": "Toggle micro function",
            "help:14488.htm": "On Key micro function",
            "help:14489.htm": "Off Key micro function",
            "help:14497.htm": "Store micro function",
            "help:14498.htm": "Downcycle micro function",
            "help:14499.htm": "Down Key micro function",
            "help:14500.htm": "Up Key micro function",
            "help:14508.htm": "End Ramp micro function",
            "help:14509.htm": "Block Retrigger Timer micro function",
            "help:14510.htm": "Block Start micro function",
            "help:14511.htm": "POT 1 Start Timer micro function",
            "help:14512.htm": "POT 1 Retrigger Timer micro function",
            "help:14514.htm": "POT 2 Retrigger Timer micro function",
        }
        live_topics = {f"help:{preset.help_topic}" for preset in macros.PRESETS.values()}
        for leaf_id, title in expected.items():
            with self.subTest(leaf_id):
                row = by_id[leaf_id]
                self.assertEqual(row["title"], title)
                self.assertEqual((row["status"], row["kind"]), ("pending", "pending"))
                self.assertEqual(row["reasons"], [{
                    "code": "special_micro_function",
                    "detail": leaf_map.REASONS["special_micro_function"],
                    "subjects": [title],
                }])
                # Negative live-code binding: no preset help_topic and no
                # wired micro-function topic covers a specialist leaf.
                self.assertNotIn(leaf_id, live_topics)
                self.assertNotIn(leaf_id, leaf_map.MICRO_WIRED_TOPICS)
        counts = committed()["counts"]
        self.assertEqual(counts["pending"], 145)
        self.assertEqual(counts["mapped_preset"] + counts["mapped_custom"]
                         + counts["mapped_micro_function"], 34)
        self.assertEqual(counts["pending_reasons"]["special_micro_function"], 16)

    def test_p001_other_key_family_subset_pins_explicit_gaps(self):
        # P0.01 census increment: the 16 other-key-family template leaves stay
        # outside the admitted classic key-macro scope; none maps to live code.
        by_id = {row["leaf_id"]: row for row in committed()["leaves"]}
        expected = {
            "help:14459.htm": "Preset macro function",
            "help:14461.htm": "On macro function",
            "help:14462.htm": "Bell press macro function",
            "help:14460.htm": "Off macro function",
            "help:14467.htm": "Off macro function",
            "help:14468.htm": "On/Off macro function",
            "help:14470.htm": "On Up macro function",
            "help:14471.htm": "Off Down macro function",
            "help:14469.htm": "Dimmer macro function",
            "help:14473.htm": "Dimmer Up macro function",
            "help:14474.htm": "Dimmer Down macro function",
            "help:14472.htm": "Timer macro function",
            "help:14475.htm": "Soft Up macro function",
            "help:14477.htm": "Preset macro function",
            "help:14476.htm": "Soft Down macro function",
            "help:14513.htm": "POT 2 Timer macro function",
        }
        live_topics = {f"help:{preset.help_topic}" for preset in macros.PRESETS.values()}
        for leaf_id, title in expected.items():
            with self.subTest(leaf_id):
                row = by_id[leaf_id]
                self.assertEqual(row["title"], title)
                self.assertEqual((row["status"], row["kind"]), ("pending", "pending"))
                self.assertEqual(row["reasons"], [{
                    "code": "other_key_family",
                    "detail": leaf_map.REASONS["other_key_family"],
                    "subjects": [title],
                }])
                # Negative live-code binding: no preset help_topic and no
                # wired micro-function topic covers an other-key-family leaf.
                self.assertNotIn(leaf_id, live_topics)
                self.assertNotIn(leaf_id, leaf_map.MICRO_WIRED_TOPICS)
        counts = committed()["counts"]
        self.assertEqual(counts["pending"], 145)
        self.assertEqual(counts["mapped_preset"] + counts["mapped_custom"]
                         + counts["mapped_micro_function"], 34)
        self.assertEqual(counts["pending_reasons"]["other_key_family"], 16)

    def test_p001_wireless_input_subset_pins_explicit_gaps(self):
        # P0.01 census increment: the 66 wireless-input leaves belong to the
        # separate wireless domain (wireless_*.py), not the classic wired
        # key-macro presets/micro-functions in macros.py; none maps to live code.
        by_id = {row["leaf_id"]: row for row in committed()["leaves"]}
        expected = {
            "help:855.htm": "Bell Press (wireless)",
            "help:872.htm": "Enable Control (wireless)",
            "help:847.htm": "Dimmer Down (wireless)",
            "help:846.htm": "Dimmer Up (wireless)",
            "help:860.htm": "Full On (wireless)",
            "help:845.htm": "Mem Toggle Dim Down Cycle (wireless)",
            "help:839.htm": "On (wireless)",
            "help:851.htm": "On Up (wireless)",
            "help:854.htm": "On Timer (wireless)",
            "help:840.htm": "Off (wireless)",
            "help:852.htm": "Off Down (wireless)",
            "help:1911.htm": "Dim Down Cycle Continuous (wireless)",
            "help:1912.htm": "Dim Up Cycle Continuous (wireless)",
            "help:841.htm": "On/Off (wireless)",
            "help:858.htm": "Preset 1 (wireless)",
            "help:859.htm": "Preset 2 (wireless)",
            "help:850.htm": "Ramp (wireless)",
            "help:856.htm": "Soft Up (wireless)",
            "help:857.htm": "Soft Dn (wireless)",
            "help:863.htm": "Scene Set (wireless)",
            "help:864.htm": "Scene Off (wireless)",
            "help:870.htm": "Scene Off Down (wireless)",
            "help:868.htm": "Scene Set Up (wireless)",
            "help:866.htm": "Scene Up (wireless)",
            "help:867.htm": "Scene Down (wireless)",
            "help:843.htm": "Toggle Dim Down Cycle (wireless)",
            "help:848.htm": "Toggle Dim Up (wireless)",
            "help:849.htm": "Toggle Dim Down (wireless)",
            "help:905.htm": "Remote Scene Trigger (wireless)",
            "help:906.htm": "Unused (wireless)",
            "help:12045.htm": "Shutter toggle (wireless)",
            "help:12046.htm": "Shutter close toggle (wireless)",
            "help:12047.htm": "Shutter open toggle (wireless)",
            "help:12048.htm": "Shutter open (wireless)",
            "help:12049.htm": "Shutter close (wireless)",
            "help:12050.htm": "Shutter stop (wireless)",
            "help:893.htm": "Decrement (wireless)",
            "help:876.htm": "DownCycle (wireless)",
            "help:1914.htm": "Dim Down Cycle Continuous (wireless)",
            "help:878.htm": "Down Key (wireless)",
            "help:904.htm": "Enable Control (wireless)",
            "help:888.htm": "End Ramp (wireless)",
            "help:891.htm": "Full On (wireless)",
            "help:895.htm": "Idle (wireless)",
            "help:892.htm": "Increment (wireless)",
            "help:877.htm": "Memory Toggle 2 (wireless)",
            "help:887.htm": "On Key (wireless)",
            "help:889.htm": "Off Key (wireless)",
            "help:880.htm": "Recall 2 (wireless)",
            "help:881.htm": "Retrigger Timer (wireless)",
            "help:883.htm": "Ramp Off (wireless)",
            "help:884.htm": "Ramp Recall 1 (wireless)",
            "help:886.htm": "Recall 1 (wireless)",
            "help:885.htm": "Toggle (wireless)",
            "help:890.htm": "Ramp (wireless)",
            "help:894.htm": "Upcycle (wireless)",
            "help:1913.htm": "Dim Up Cycle Continuous (wireless)",
            "help:879.htm": "Up Key (wireless)",
            "help:897.htm": "Scene Set (wireless)",
            "help:898.htm": "Scene Up (wireless)",
            "help:899.htm": "Scene Off (wireless)",
            "help:900.htm": "Scene Down (wireless)",
            "help:902.htm": "Scene Toggle (wireless)",
            "help:903.htm": "Scene Stop (wireless)",
            "help:875.htm": "Store 1 (wireless)",
            "help:882.htm": "Start (wireless)",
        }
        live_topics = {f"help:{preset.help_topic}" for preset in macros.PRESETS.values()}
        for leaf_id, title in expected.items():
            with self.subTest(leaf_id):
                row = by_id[leaf_id]
                self.assertEqual(row["title"], title)
                self.assertEqual((row["status"], row["kind"]), ("pending", "pending"))
                self.assertEqual(row["reasons"], [{
                    "code": "wireless_input",
                    "detail": leaf_map.REASONS["wireless_input"],
                    "subjects": [title],
                }])
                # Negative live-code binding: no preset help_topic and no
                # wired micro-function topic covers a wireless-input leaf.
                self.assertNotIn(leaf_id, live_topics)
                self.assertNotIn(leaf_id, leaf_map.MICRO_WIRED_TOPICS)
        counts = committed()["counts"]
        self.assertEqual(counts["pending"], 145)
        self.assertEqual(counts["mapped_preset"] + counts["mapped_custom"]
                         + counts["mapped_micro_function"], 34)
        self.assertEqual(counts["pending_reasons"]["wireless_input"], 66)

    def test_offline_rebuild_is_deterministic_and_byte_identical(self):
        document = committed()
        surface = json.loads((ROOT / "docs/toolkit-surface.json").read_text(encoding="utf-8"))
        facts = leaf_map.facts_of({"macro_reference": surface["macro_reference"]})
        presets, codes = leaf_map.live_tables()
        first = leaf_map.render(leaf_map.build_document(facts, presets, codes))
        second = leaf_map.render(leaf_map.build_document(facts, presets, codes))
        self.assertEqual(first, second)
        self.assertEqual(first, MAP_PATH.read_text(encoding="utf-8"))

    def test_tampered_or_missing_input_digests_are_rejected(self):
        document = committed()
        for name in ("surface", "macros"):
            with self.subTest(name):
                mutated = copy.deepcopy(document)
                mutated["inputs"][name]["sha256"] = "0" * 64
                with self.assertRaisesRegex(ValueError, f"input changed: {name}"):
                    leaf_map.validate_document(mutated)

    def test_pending_rows_require_an_explicit_known_reason(self):
        unresolved = next(
            index
            for index, row in enumerate(committed()["leaves"])
            if row["status"] == "pending"
        )
        cases = {
            "empty reasons": lambda row: row.update(reasons=[]),
            "unknown code": lambda row: row.update(
                reasons=[{"code": "looks_fine", "detail": "x", "subjects": ["y"]}]
            ),
            "altered detail": lambda row: row["reasons"][0].update(detail="x"),
            "extra reason field": lambda row: row["reasons"][0].update(note="x"),
            "claimed mapping": lambda row: row.update(status="mapped"),
            "unknown status": lambda row: row.update(status="partial"),
        }
        for label, mutate in cases.items():
            with self.subTest(label):
                document = committed()
                mutate(document["leaves"][unresolved])
                with self.assertRaises(ValueError):
                    leaf_map.validate_document(document)


if __name__ == "__main__":
    unittest.main()
