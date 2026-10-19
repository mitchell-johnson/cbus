"""P8.02 wave-26 narrow offline pin for #56 (usage guards).

Pins pure-offline guards in
``cbus_toolkit.project_documentation_usage`` only: the lookup
constants, the group-kind guard, and the unknown unit/action
fallbacks. No server, hardware, GUI, vendor EXE, eDLT, wireless,
firmware, Rust, or parity-register claim; #56 stays OPEN.

Each pinned guard below had zero prior refs in ``tests/``:
``usage.GROUP_LABELS``, ``usage.DIGITAL_CHANNEL_COUNT``,
``usage.NO_INDICATOR_BRIGHTNESS``, ``usage.DIGITAL_ACTIONS``,
``usage.CLASSIC_OUTPUT_CHANNELS`` / ``usage.DIRECT_ACTIONS`` as
``usage.<name>`` references, the ``Group usage kind must be input,
output or other`` guard, the ``unit group dependency
implementation`` fallback, and the ``ActionSelectorUse
implementation`` fallback.
"""

from __future__ import annotations

import unittest

from cbus_toolkit import project_documentation as doc
from cbus_toolkit import project_documentation_usage as usage


def _unit(unit_type="BURDEN", params=None):
    return doc.Unit(1, "U1", unit_type, unit_type, "", "1.0.00", "",
                    dict(params or {}), {})


class UsageLookupConstantsWave26Tests(unittest.TestCase):
    def test_lookup_constants_exact(self):
        # Next: native per-unit description text beyond these keys stays open.
        self.assertEqual(usage.CLASSIC_OUTPUT_CHANNELS,
                         {"RELAY1": 1, "RELAY2": 2, "RELAY4": 4,
                          "DIMMER4": 4, "AN_OUT4": 4})
        self.assertEqual(usage.DIRECT_ACTIONS, {
            "FanController": ("RELDF1", "FanTriggerGroup",
                              "FanActionSelector", "Fan Speed Cycle"),
            "SENTEMPPro": ("SENTEMPB", "BroadcastTriggerGroup",
                           "BroadcastTriggerLevel",
                           "Trigger Temperature Broadcast"),
        })
        self.assertEqual(usage.DIGITAL_ACTIONS, (
            ("ErrorReportingTriggerGroup", "ErrorReportingActionSelector",
             "Trigger Error Report"),
            ("BroadcastTriggerGroup", "BroadcastActionSelector",
             "Trigger Temperature Report"),
        ))
        self.assertEqual(usage.DIGITAL_CHANNEL_COUNT, 4)
        self.assertEqual(usage.NO_INDICATOR_BRIGHTNESS,
                         frozenset({"KEYBC2", "KEYBC4", "KEYAUX4",
                                    "DINAUX4", "BCNC4A", "BCNC4B"}))
        self.assertEqual(usage.GROUP_LABELS,
                         ("Channel %d", "Logic Group",
                          "Logic Group (Unused)", "Key %d",
                          "Block (Unused)", "Area Group",
                          "Indicator Brightness Group"))


class GroupKindGuardWave26Tests(unittest.TestCase):
    def test_bad_kind_rejected_before_lookup(self):
        # Next: native group-section ordering beyond the kind gate stays open.
        with self.assertRaisesRegex(ValueError, "Group usage kind must be"):
            usage.group_usage(_unit(), 56, 1, "bogus")
        with self.assertRaisesRegex(ValueError, "Group usage kind must be"):
            usage.group_usage(_unit(), 56, 1, "")


class UnknownUnitFallbackWave26Tests(unittest.TestCase):
    def test_unknown_unit_group_dependency_unrecovered(self):
        # Next: native per-type group dependency admission stays open.
        for kind in ("input", "output", "other"):
            result = usage.group_usage(_unit("BURDEN"), 56, 1, kind)
            self.assertEqual(result.status, "unrecovered")
            self.assertEqual(result.missing,
                             ("unit group dependency implementation",))
            self.assertEqual(result.html, "")


class UnknownActionFallbackWave26Tests(unittest.TestCase):
    def test_unknown_action_selector_implementation_unrecovered(self):
        # Next: native ActionSelectorUse admission beyond this gate stays open.
        result = usage.action_selector_usage(
            _unit("BURDEN"), "BogusDocumentor", 56, 1, 2, 3)
        self.assertEqual(result.status, "unrecovered")
        self.assertEqual(result.missing, ("ActionSelectorUse implementation",))
        self.assertEqual(result.html, "")


if __name__ == "__main__":
    unittest.main()
