"""Wave-20 offline pins for wireless-scenes guards (P5.07, issue 44).

Each test pins a branch of ``toolkit-cli/src/cbus_toolkit/wireless_scenes.py``
with zero prior test refs (verified via grep -rn across tests/ before writing):
- ``_scenes`` unused-trigger guard: grep -rn "Unused trigger group requires" -> 0 hits.
- ``_scenes`` duplicate-group guard: grep -rn "A scene cannot add the same group twice" -> 0 hits.
- ``decode`` sparse-offset guard: grep -rn "Sparse or invalid scene offsets" -> 0 hits.
- ``decode`` ramp-enum guard: grep -rn "outside the original enum range" -> 0 hits.
- ``decode`` terminator/crossing guards: grep -rn "Scene vector lacks a terminator" /
  "Scene command crosses the vector boundary" -> 0 hits.

Pure offline: ``_scenes``/``decode`` only, no hardware, vendor EXE, C-Gate
server, PP session, or decoded vendor spec. Issue 44 stays OPEN.
"""
from __future__ import annotations

import unittest

from cbus_toolkit.wireless_scenes import WirelessScenesError, _scenes, decode


def base_current(**overrides):
    current = {
        "SceneTriggerGroup": (10,) * 8,
        "SceneTriggerLevel": (20,) * 8,
        "SceneTriggerRate": (0,) * 8,
        "SceneVectorOffset": (255,) * 8,
        "SceneVector": (255,) * 100,
    }
    current.update(overrides)
    return current


class ScenesInputWave20Tests(unittest.TestCase):
    def test_unused_trigger_group_requires_unused_action_selector(self):
        with self.assertRaisesRegex(
            WirelessScenesError, "Unused trigger group requires unused action selector"
        ):
            _scenes([
                {"application": "primary", "trigger_group": 255,
                 "trigger_level": 20, "rate": 0, "entries": []},
            ])

    def test_scene_cannot_add_same_group_twice(self):
        with self.assertRaisesRegex(
            WirelessScenesError, "A scene cannot add the same group twice"
        ):
            _scenes([
                {"application": "primary", "trigger_group": 10,
                 "trigger_level": 20, "rate": 0,
                 "entries": [{"group": 7, "level": 0}, {"group": 7, "level": 1}]},
            ])


class DecodeGuardsWave20Tests(unittest.TestCase):
    def test_sparse_offset_after_unused_requires_review(self):
        current = base_current(
            SceneVectorOffset=(255, 0, 255, 255, 255, 255, 255, 255),
        )
        with self.assertRaisesRegex(
            WirelessScenesError,
            "Sparse or invalid scene offsets require original load dependency review",
        ):
            decode(current)

    def test_ramp_rate_outside_original_enum_refused(self):
        current = base_current(
            SceneVectorOffset=(0, 255, 255, 255, 255, 255, 255, 255),
            SceneTriggerRate=(16, 0, 0, 0, 0, 0, 0, 0),
        )
        with self.assertRaisesRegex(
            WirelessScenesError,
            "Configured scene ramp rate is outside the original enum range",
        ):
            decode(current)

    def test_missing_terminator_and_boundary_crossing_refused(self):
        no_terminator = base_current(
            SceneVectorOffset=(0, 255, 255, 255, 255, 255, 255, 255),
            SceneVector=tuple(range(100)),
        )
        with self.assertRaisesRegex(
            WirelessScenesError, "Scene vector lacks a terminator"
        ):
            decode(no_terminator)
        crossing = base_current(
            SceneVectorOffset=(99, 255, 255, 255, 255, 255, 255, 255),
            SceneVector=(255,) * 99 + (7,),
        )
        with self.assertRaisesRegex(
            WirelessScenesError, "Scene command crosses the vector boundary"
        ):
            decode(crossing)


if __name__ == "__main__":
    unittest.main()
