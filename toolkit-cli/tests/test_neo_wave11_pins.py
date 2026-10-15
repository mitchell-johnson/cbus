"""Wave 11 narrow offline pins for P5 Neo/key inputs (issue #39).

Each method pins ONE pure-offline branch in neo_indicators.py or
key_options_cli.py with a synthetic fixture or plain values: no hardware,
vendor EXE, C-Gate server, or decoded vendor spec is required. Complements
round 13 (full guard messages) and test_input_options.py (happy paths,
substrings) with the adjacent unpinned details: source-code percent
mapping, non-Neo admission, the style off-colour matrix, the reflection
family nightlight bit, and the CLI adapter's explicit-False filter.
#39 stays OPEN; join/IR/virtual-key columns remain untouched.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from test_input_options import fixture as input_fixture

from cbus_toolkit.key_options_cli import _settings
from cbus_toolkit.neo_indicators import (
    OPTION_LAYOUTS,
    STYLE_LAYOUTS,
    NeoIndicatorOptions,
    NeoIndicatorStyles,
    brightness_to_percent,
    percent_to_brightness,
)
from cbus_toolkit.pp_editor import PPEditError


class BrightnessMappingWave11Tests(unittest.TestCase):
    """Source codes map to no percent; Toolkit integer-math remaps roundtrip."""

    def test_source_codes_have_no_percent_and_remaps_roundtrip(self):
        # Next: key_options_cli.py brightness staging; no PP/save here.
        for value in (0, 1, 2, 3):
            with self.subTest(value=value):
                self.assertIsNone(brightness_to_percent(value))
        self.assertEqual(
            [(brightness_to_percent(v), v) for v in (4, 5, 6, 7)],
            [(0, 4), (1, 5), (2, 6), (3, 7)],
        )
        self.assertEqual(brightness_to_percent(255), 100)
        self.assertEqual(brightness_to_percent(252), 99)
        self.assertTrue(all(4 <= percent_to_brightness(p) <= 255 for p in range(101)))


class ProfileAdmissionWave11Tests(unittest.TestCase):
    """Non-Neo profiles refused; reflection uses the PCx nightlight bit."""

    def test_non_neo_profile_refused_and_reflection_uses_pcx(self):
        # Next: extended_macros.py PROFILES; no wizard state here.
        for filename, unit_type in (("NOPE.xml", "NOPE"), ("KEYM4.xml", "KEYB4")):
            with self.subTest(filename=filename, unit_type=unit_type):
                with self.assertRaisesRegex(
                    PPEditError, "supports the admitted Neo-core profiles only"
                ):
                    NeoIndicatorOptions(input_fixture(filename, unit_type, OPTION_LAYOUTS))
                with self.assertRaisesRegex(
                    PPEditError, "supports the admitted Neo-core profiles only"
                ):
                    NeoIndicatorStyles(input_fixture(filename, unit_type, STYLE_LAYOUTS))
        reflection = NeoIndicatorOptions(input_fixture("KEYA3.xml", "KEYA3", OPTION_LAYOUTS))
        self.assertEqual(reflection.nightlight_parameter, "EnableNightlightOnPCx")
        plan = reflection.plan(
            dict(reflection.spec.defaults()),
            key_press_level=9,
            key_press_seconds=4,
            nightlight=True,
        )
        self.assertEqual(plan.changes["EnableNightlightOnPCx"], (1,))
        self.assertEqual(plan.as_dict()["nightlight_parameter"], "EnableNightlightOnPCx")


class StyleDetailsWave11Tests(unittest.TestCase):
    """Omitted style leaves each key's function; off-colour follows the matrix."""

    def test_style_none_keeps_function_and_off_colour_matrix(self):
        # Next: neo_indicator_editor.py per-LED panel; no bulk write here.
        styles = NeoIndicatorStyles(input_fixture("KEYM4.xml", "KEYM4", STYLE_LAYOUTS))
        current = styles.spec.defaults()
        kept = styles.plan(dict(current), colour="blue")
        self.assertEqual(kept.changes, {"PrimaryColour": (0,) * 8})
        self.assertEqual(kept.as_dict()["off_colour"], "orange")
        self.assertFalse(kept.as_dict()["avanti_colour_note"])
        fixed = styles.plan(dict(current), colour="blue", style="always_off")
        self.assertEqual(fixed.changes["IndicatorFunction"], (0,) * 8)
        self.assertIsNone(fixed.as_dict()["off_colour"])
        dual = styles.plan(dict(current), colour="orange", style="status_dual")
        self.assertEqual(dual.changes, {"IndicatorFunction": (3,) * 8})
        self.assertEqual(dual.as_dict()["off_colour"], "blue")
        avanti = NeoIndicatorStyles(input_fixture("KEYV2.xml", "KEYV2", STYLE_LAYOUTS))
        self.assertTrue(
            avanti.plan(dict(current), colour="blue", style="always_on").as_dict()[
                "avanti_colour_note"
            ]
        )


class IndicatorAdapterWave11Tests(unittest.TestCase):
    """CLI adapter keeps explicit False; first-block/fixed details decode."""

    def test_adapter_keeps_explicit_false_and_details_decode(self):
        # Next: native key_options_cli.py configure(); no session here.
        method, options = _settings(
            "neo-indicator-plan",
            SimpleNamespace(
                brightness="first_block",
                brightness_percent=None,
                brightness_group=None,
                key_press_level=None,
                key_press_seconds=None,
                nightlight=None,
                ignore_first_key_press=None,
                timer_flash=False,
                id_backlight=False,
            ),
            object(),
        )
        self.assertEqual(
            (method, options),
            (
                "plan",
                {
                    "brightness": "first_block",
                    "timer_flash": False,
                    "id_backlight": False,
                },
            ),
        )
        editor = NeoIndicatorOptions(input_fixture("KEYM4.xml", "KEYM4", OPTION_LAYOUTS))
        plan = editor.plan(dict(editor.spec.defaults()), **options)
        self.assertEqual(plan.changes["IndicatorBrightness"], (1,))
        self.assertEqual(
            plan.as_dict()["brightness"],
            {"source": "first_block", "percent": None, "group": None},
        )
        fixed = editor.plan(
            dict(editor.spec.defaults()), brightness="fixed", brightness_percent=0
        )
        self.assertEqual(fixed.changes, {"IndicatorBrightness": (4,)})
        self.assertEqual(
            fixed.as_dict()["brightness"],
            {"source": "fixed", "percent": 0, "group": None},
        )


if __name__ == "__main__":
    unittest.main()
