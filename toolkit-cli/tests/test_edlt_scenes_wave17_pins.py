"""Wave-17 offline pins for SceneManager constructor/envelope guards.

Pure offline checks against toolkit-cli/src/cbus_toolkit/edlt_scene_manager.py
only: dataclass bound guards, the static operation envelope and the cache
envelope. No fixtures, no unitspec, no network, no wheel.
"""
import unittest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_scene_manager import (
    EdltSceneManager,
    SceneCaptureLevel,
    SceneDynamicLabel,
    SceneLevelLabels,
    SceneManagerCache,
)


def _label(value="v", name="n", image_present=False):
    return SceneDynamicLabel(value, name, image_present)


class SceneManagerWave17PinTests(unittest.TestCase):
    def test_dynamic_label_bounds_reject_oversize_and_non_boolean(self):
        with self.assertRaisesRegex(EdltError, "bounded strings"):
            SceneDynamicLabel("x" * 1025, "n", False)
        with self.assertRaisesRegex(EdltError, "bounded strings"):
            SceneDynamicLabel("v", "y" * 1025, False)
        with self.assertRaisesRegex(EdltError, "bounded strings"):
            SceneDynamicLabel("v", "n", 1)
        with self.assertRaises(EdltError):
            SceneDynamicLabel(7, "n", False)
        valid = _label()
        self.assertEqual(valid.as_dict(), {"value": "v", "name": "n", "image_present": False})

    def test_level_labels_reject_non_tuple_overfull_and_mistyped(self):
        with self.assertRaisesRegex(EdltError, "at most four label objects"):
            SceneLevelLabels(0, 0, tuple(_label(str(i)) for i in range(5)))
        with self.assertRaisesRegex(EdltError, "at most four label objects"):
            SceneLevelLabels(0, 0, [_label()])
        with self.assertRaisesRegex(EdltError, "at most four label objects"):
            SceneLevelLabels(0, 0, ("not-a-label",))
        valid = SceneLevelLabels(0, 0, (_label(),))
        self.assertEqual(valid.as_dict()["labels"], [_label().as_dict()])

    def test_capture_level_constructor_rejects_bounds_and_non_boolean(self):
        with self.assertRaises(EdltError):
            SceneCaptureLevel(0, 0, True)
        with self.assertRaises(EdltError):
            SceneCaptureLevel(65537, 0, True)
        with self.assertRaises(EdltError):
            SceneCaptureLevel(True, 0, True)
        with self.assertRaises(EdltError):
            SceneCaptureLevel(1, 256, True)
        with self.assertRaisesRegex(EdltError, "boolean"):
            SceneCaptureLevel(1, 0, 1)
        valid = SceneCaptureLevel(1, 0, True)
        self.assertEqual(valid.as_dict(), {"item_id": 1, "level": 0, "verified": True})

    def test_operation_and_cache_envelopes_reject_malformed(self):
        with self.assertRaisesRegex(EdltError, "requires an op field"):
            EdltSceneManager._operation({})
        with self.assertRaisesRegex(EdltError, "requires an op field"):
            EdltSceneManager._operation({"op": 1, "scene": 1})
        with self.assertRaisesRegex(EdltError, "requires an op field"):
            EdltSceneManager._operation(["op"])
        with self.assertRaisesRegex(EdltError, "Invalid SceneManager cache"):
            SceneManagerCache.from_dict({})
        with self.assertRaisesRegex(EdltError, "Invalid SceneManager cache"):
            SceneManagerCache.from_dict({"format": "cbus-edlt-scene-manager-cache-v1"})
        with self.assertRaisesRegex(EdltError, "requires ApplicationCache"):
            SceneManagerCache("not-a-cache", ())


if __name__ == "__main__":
    unittest.main()
