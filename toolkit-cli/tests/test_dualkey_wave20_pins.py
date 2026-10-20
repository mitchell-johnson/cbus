"""P6 wave-20 narrow offline pin for #45 (dual-key controls).

One narrow slice of edlt_dual_key_controls.py guards with zero prior
refs in tests and literal vectors: choice_identity prefix/refusal,
level-validating rewrite, level-advanced empty handler, plus read-only
get-used-static-text and timer-get no-ops. Pure-offline only: no
server, GUI, hardware, PP, or original execution. #45 stays OPEN;
Rust, edlt_mra, wireless_gateway, firmware_update_plan,
wireless_scenes, firmware_update_run, and parity register stay untouched.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from cbus_toolkit.edlt import EdltError, _field
from cbus_toolkit import edlt_dual_key_controls as controls

FIXTURE = Path(__file__).resolve().parents[1] / "research/fixtures/edlt-dual-key-control-literal-vectors.json"
VECTORS = json.loads(FIXTURE.read_text())
NAMES = tuple(f"Name {i}" for i in range(64))


def _timer_record():
    case = next(c for c in VECTORS["control_cases"] if c["family"] == "timer")
    return case["record_before_hex"], case.get("restore_level", 91)


def _values(record, restore=91):
    values = {_field(6, i): (val,) for i, val in enumerate(record)}
    values.update({_field(7, i): (val,) for i, val in enumerate(bytes(range(32)))})
    values["Widget6RestoreLevel"] = (restore,)
    values["Widget7RestoreLevel"] = (177,)
    values.update({f"StaticTextString{i}": tuple([0] * 64) for i in range(64)})
    values.update(UseBigIcon=(1,), UnitName="Exact text",
                  Scene8StartAddress=(65535,), Unrelated=(19, 32, 77))
    return values


def _runtime(events, family="timer"):
    record_hex, restore = _timer_record()
    values = _values(bytes.fromhex(record_hex), restore)
    owner = object()
    operation = {"op": family, "dual_key_controls": events}
    binding = controls.issue_dual_key_control_binding(
        owner=owner, operation=operation, values=values,
        family=family, widget=6, retained_names=NAMES,
        external_used_indices=(1, 9, 200, 255))
    return owner, operation, values, binding


class P45ChoiceIdentityWave20Tests(unittest.TestCase):
    """Offered-list identity prefixes; icon/unknown bindings have none."""

    def test_prefix_map_and_icon_refusal(self):
        # Next: #45 dual-key bindings only; no mra/gateway/firmware/parity here.
        self.assertEqual(controls.choice_identity("timer", "ramp-rate", 3), "dual-key-ramp:3")
        self.assertEqual(controls.choice_identity("room-courtesy", "on-colour", 4), "dual-key-colour:4")
        self.assertEqual(controls.choice_identity("room-courtesy", "off-colour", 8), "dual-key-colour:8")
        self.assertEqual(controls.choice_identity("shutter", "macro", 0), "dual-key-shutter-macro:0")
        for family, target in (("timer", "icon-on"), ("timer", "icon-off"),
                               ("shutter", "icon-on"), ("room-courtesy", "icon-on")):
            with self.assertRaises(EdltError):
                controls.choice_identity(family, target, 1)
        with self.assertRaises(EdltError):
            controls.choice_identity("timer", "macro", 1)
        with self.assertRaises(EdltError):
            controls.choice_identity("nope", "ramp-rate", 1)


class P45LevelValidatingWave20Tests(unittest.TestCase):
    """Validating rewrites the current control value; levels stay put."""

    def test_validating_rewrites_current_value(self):
        # Next: same #45 boundary; no modal/trackbar/numeric dispatch here.
        events = [{"event": "level-set", "target": "expiry", "value": 17},
                  {"event": "level-validating", "target": "expiry"}]
        owner, op, values, binding = _runtime(events)
        result = controls.project_dual_key_controls(
            binding, owner=owner, operation=op, values=values, retained_names=NAMES)
        journal = result.as_dict()["journal"]
        self.assertEqual(journal[1]["binding_callbacks"],
                         [{"action": "Binding.WriteValue", "target": "expiry", "value": 17}])
        self.assertEqual(journal[1]["observed"]["value"], 17)
        self.assertEqual(result.as_dict()["state"]["levels"]["expiry"]["value"], 17)


class P45LevelAdvancedWave20Tests(unittest.TestCase):
    """Advanced click is an empty handler; record does not move."""

    def test_advanced_empty_handler_without_record_change(self):
        # Next: same #45 boundary; no framework dispatch or device write.
        events = [{"event": "level-advanced", "target": "expiry"}]
        owner, op, values, binding = _runtime(events)
        result = controls.project_dual_key_controls(
            binding, owner=owner, operation=op, values=values, retained_names=NAMES)
        journal = result.as_dict()["journal"]
        self.assertEqual(journal[0]["binding_callbacks"],
                         [{"action": "AdvancedClick.EmptyHandler"}])
        self.assertEqual(journal[0]["record_before_hex"], journal[0]["record_after_hex"])
        self.assertEqual(journal[0]["observed"]["value"], 0)


class P45ReadOnlyNoopWave20Tests(unittest.TestCase):
    """get-used-static-text and timer-get observe without side effects."""

    def test_used_static_text_and_timer_get_are_read_only(self):
        # Next: same #45 boundary; no property write or timer store here.
        owner, op, values, binding = _runtime([{"event": "get-used-static-text"}])
        result = controls.project_dual_key_controls(
            binding, owner=owner, operation=op, values=values, retained_names=NAMES)
        journal = result.as_dict()["journal"]
        self.assertIsInstance(journal[0]["observed"], list)
        self.assertEqual(journal[0]["binding_callbacks"], [])
        self.assertEqual(journal[0]["record_before_hex"], journal[0]["record_after_hex"])

        owner2, op2, values2, binding2 = _runtime([{"event": "timer-get"}])
        result2 = controls.project_dual_key_controls(
            binding2, owner=owner2, operation=op2, values=values2, retained_names=NAMES)
        journal2 = result2.as_dict()["journal"]
        self.assertEqual(journal2[0]["observed"], 0)
        self.assertEqual(journal2[0]["binding_callbacks"], [])
        self.assertEqual(journal2[0]["record_before_hex"], journal2[0]["record_after_hex"])


if __name__ == "__main__":
    unittest.main()
