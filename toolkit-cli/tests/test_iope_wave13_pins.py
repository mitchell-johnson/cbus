"""P5 IOPE wave-13 narrow offline pins (issue #40 follow-up).

Pins one narrow slice of ``iope_settings.py`` guards with a synthetic
fixture only: join/power-up-broadcast block guards, scene ramp/recall
guards, sensor-enable join guards, and settings identity/output/firmware
guards. No hardware, vendor EXE, C-Gate server, or decoded vendor spec is
required; every refusal fires before any I/O.

Zero-prior-refs method: before writing, each full message string below was
checked with ``grep -rF --include='*.py' <message> tests/`` and returned
zero hits (existing tests pin only short substrings such as "both",
"shared", "either", "global1" or "255" for these branches, never the full
guard text pinned here).
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from cbus_toolkit.iope_settings import (
    BLOCKS,
    LAYOUTS,
    PROFILES,
    IopeSettings,
    timer_seconds,
)
from cbus_toolkit.pp_editor import PPEditError
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec

FIRMWARE = "1.2.00"

# Synthetic defaults mirroring test_iope_settings.py: bistable aux 1 on
# block 1 with a group, block 2 grouped but only momentary, block 3
# ungrouped. Keeps block 1 eligible and blocks 2..3 ineligible.
DEFAULTS = {"Memory1": [128], "Memory2": [153], "Memory3": [191], "Memory4": [230], "LongPressTime": [25],
            "RampRateA": [1], "RampRateB": [2], "RampRateC": [3], "RampRateS": [1], "ClockGenEnable": [1],
            "Sensor1EnableGroupInEnableControlApp": [1], "Sensor2EnableGroupInEnableControlApp": [1],
            "BistableAuxiliary1": [1], "TimerHighByte": [1] * 8, "TimerLowByte": [44] * 8,
            "InputGroupAddress": [10, 11] + [255] * 6, "OutputGroupAddress": [20, 21, 22, 23],
            "Sensor1EnableGroup": [255], "Sensor2EnableGroup": [255], "StatusReportInterval": [3],
            "GroupAssertOnPowerup": [0b110], "Auxiliary1BlockAllocation": [1, 0, 1, 0, 0, 0, 0, 0],
            "Auxiliary2BlockAllocation": [0, 1, 0, 0, 0, 0, 0, 0]}


def fixture(unit_type="IOPE2C4"):
    parameters = {}
    for name, (kind, address, size, bits, bit, skip) in LAYOUTS.items():
        fields = {"Name": name, "Type": kind, "Address": str(address), "ArraySize": str(size),
                  "BitAddress": str(bit), "ArraySkip": str(skip),
                  "DefaultValue": " ".join(map(str, DEFAULTS.get(name, [0] * size)))}
        if kind == "int":
            fields.update(BitSize=str(bits), MinValue="0", MaxValue=str((1 << bits) - 1))
        parameters[name] = ParameterSpec(name, kind, "literal-iope-fixture.xml", fields)
    return UnitSpec(unit_type + ".xml", {"Type": unit_type}, ("literal-iope-fixture.xml",), parameters)


def values(**overrides):
    result = {name: " ".join(map(str, DEFAULTS.get(name, [0] * layout[2]))) for name, layout in LAYOUTS.items()}
    result.update({k: " ".join(map(str, v)) for k, v in overrides.items()})
    return result


class IopeWave13PinsTest(unittest.TestCase):
    def editor(self, unit_type="IOPE2C4"):
        return IopeSettings(fixture(unit_type))

    def test_join_broadcast_block_shape_and_overlap_guards(self):
        """Join/power-up broadcast block guards (zero prior full-message refs)."""
        editor = self.editor()
        with self.assertRaisesRegex(PPEditError, "Blocks must be a list of block numbers"):
            editor.plan(values(), enable_broadcast="1")
        with self.assertRaisesRegex(PPEditError, "Blocks must be a list of block numbers"):
            editor.plan(values(), disable_broadcast=5)
        with self.assertRaisesRegex(PPEditError, "A block cannot be both enabled and disabled"):
            editor.plan(values(), enable_broadcast=[1], disable_broadcast=[1])
        # Block 2 is grouped but only on the momentary auxiliary, so the
        # Toolkit save would clear it; the full save-as-off refusal is pinned.
        with self.assertRaisesRegex(
            PPEditError, "Toolkit saves their power-up broadcast as off"
        ):
            editor.plan(values(), enable_broadcast=[2])

    def test_scene_ramp_and_recall_guards(self):
        """Scene ramp/recall guards (zero prior full-message refs)."""
        editor = self.editor()
        with self.assertRaisesRegex(
            PPEditError, "Ramp rates are global1, global2, global3 and scene"
        ):
            editor.plan(values(), ramp_rates={"global4": 1})
        with self.assertRaisesRegex(
            PPEditError, "Use either a raw recall level or a percentage for each global"
        ):
            editor.plan(values(), recall_levels={1: 1}, recall_percents={1: 50})
        with self.assertRaisesRegex(
            PPEditError, "Use either recovery_level or recovery_percent"
        ):
            editor.plan(values(), outputs={1: {"recovery_level": 3, "recovery_percent": 30}})
        # Scene ramp happy path still resolves the scene field label.
        plan = editor.plan(values(), ramp_rates={"scene": "8 secs"})
        self.assertEqual(plan.changes["RampRateS"], (2,))

    def test_sensor_enable_join_guards(self):
        """Sensor-enable join guards (zero prior full-message refs)."""
        editor = self.editor()
        with self.assertRaisesRegex(PPEditError, "Unknown sensor options"):
            editor.plan(values(), sensors={1: {"bogus": 1}})
        with self.assertRaisesRegex(PPEditError, "disabled_when must be on or off"):
            editor.plan(values(), sensors={1: {"disabled_when": "sometimes"}})
        with self.assertRaisesRegex(
            PPEditError, "enable_application must be primary or enable-control"
        ):
            editor.plan(values(), sensors={1: {"enable_application": "bogus"}})
        with self.assertRaisesRegex(
            PPEditError, "state_recovery must be enabled, disabled or restore"
        ):
            editor.plan(values(), sensors={1: {"state_recovery": "bogus"}})

    def test_settings_identity_output_and_firmware_guards(self):
        """Settings identity/output/firmware guards (zero prior full-message refs)."""
        editor = self.editor()
        with self.assertRaisesRegex(PPEditError, "Unit identity is not admitted"):
            editor.plan(values(), identity=("IOPE1R1", "1.2.00"))
        with self.assertRaisesRegex(PPEditError, "Unit identity is not admitted"):
            editor.plan(values(), identity=("IOPE2C4", "9.9.99"))
        with self.assertRaisesRegex(PPEditError, "Unknown output options"):
            editor.plan(values(), outputs={1: {"bogus": True}})
        with self.assertRaisesRegex(
            PPEditError, "Auto Level Store is enabled; Toolkit saves the recovery level as 255"
        ):
            editor.plan(values(LevelStoreEnable=[1, 0, 0, 0]), outputs={1: {"recovery_level": 3}})
        with self.assertRaisesRegex(
            PPEditError, "Output recovery on a group shared by another channel is not admitted"
        ):
            editor.plan(
                values(OutputGroupAddress=[20, 20, 22, 23]),
                outputs={1: {"recovery_level": 3}},
            )
        # Stale-firmware apply guard fires before any native I/O.
        plan = editor.plan(values(), identity=("IOPE2C4", FIRMWARE), long_press=40)
        session = SimpleNamespace(
            unit_type="IOPE2C4", firmware="1.1.00",
            catalog_number=PROFILES["IOPE2C4"].catalog_number,
        )
        with self.assertRaisesRegex(PPEditError, "Plan was created for another firmware"):
            editor.apply(session, plan)
        # Timer entry guards pin the documented H:MM:SS and range text.
        with self.assertRaisesRegex(PPEditError, "Timer must be seconds or H:MM:SS"):
            timer_seconds("nope")
        with self.assertRaisesRegex(PPEditError, r"Timer must be 0\.\.65535"):
            timer_seconds(65536)
        self.assertEqual(BLOCKS, 8)


if __name__ == "__main__":
    unittest.main()
