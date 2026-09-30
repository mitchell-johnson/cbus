"""Neo-core indicator options and indicator styles from Toolkit 1.18.

These are the Unit Magic "Indicator Options" (TfrmNeoIndicatorOptions) and
"Input Unit Indicator Styles and Colours" (TfrmNeoLED) pages. Values follow
the C-Gate agent save path for each Toolkit class:

* TCoreKeyInputCGateAgent.SetIndicatorBrightness writes $04..$FF for a fixed
  level, $00 for the level of the brightness group (the ninth GroupAddress)
  and $01 for the level of the first block.
* TCoreNeoInputCGateAgent.BeforeSaveProgrammingInformation writes
  IndicatorPressedLevel, TimerDuration (key-press brightening duration),
  FirstKeyThrowAway and DisableTimerFlash (inverse of timer flash).
* TCBusNeoInputCGateAgent writes IDBacklightIllumination, EnableNightlight
  (always false) and the nightlight bit: EnableNightlightOnPA6 for
  IsNeoStandard classes, EnableNightlightOnPCx for Reflection and Saturn.
* The indicator style is IndicatorFunction 0..3 and the on colour is
  PrimaryColour 0 (blue) or 1 (orange) for every key entry.

Options are optional here: None keeps the current value. The Toolkit wizard
overwrites every option; pass all of them to reproduce it.
"""
from __future__ import annotations

from types import MappingProxyType

from .extended_macros import PROFILES
from .pp_editor import PPEditError, PPEditor, boolean, integer

# IsNeoStandard / IsNeoSaturn / IsNeoReflection / IsNeoClassic virtual results
# of each admitted Toolkit class (research/key_preset_families.py receipt).
FAMILIES = MappingProxyType({
    **{name: "standard" for name in ("KEYM2", "KEYM4", "KEYM8", "KEYDV1", "KEYDV2", "KEYDV3", "KEYDV4")},
    **{name: "saturn" for name in ("KEYB2", "KEYB4", "KEYB6", "KEYE1", "KEYH1", "KEYH2", "KEYH3", "KEYH4",
                                   "KEYP2", "KEYP4", "KEYP6", "KEYV1", "KEYV2", "KEYV3")},
    **{name: "reflection" for name in ("KEYA1", "KEYA3", "KEYA6", "KEYA8", "KEYAV2", "KEYAV4")},
    **{name: "classic" for name in ("KEYC1", "KEYC2", "KEYC4", "KEYCIR4")},
})
AVANTI = frozenset({"KEYV1", "KEYV2", "KEYV3"})
OPTION_LAYOUTS = MappingProxyType({
    "IndicatorBrightness": ("int", 0x32, 1, 8, 0, 0),
    "GroupAddress": ("int", 0x50, 9, 8, 0, 0),
    "IndicatorPressedLevel": ("int", 0x33, 1, 4, 4, 0),
    "TimerDuration": ("int", 0x33, 1, 4, 0, 0),
    "EnableNightlight": ("bit", 0x34, 1, 1, 0, 0),
    "DisableTimerFlash": ("bit", 0x34, 1, 1, 1, 0),
    "IDBacklightIllumination": ("bit", 0x34, 1, 1, 3, 0),
    "FirstKeyThrowAway": ("bit", 0x34, 1, 1, 4, 0),
    "EnableNightlightOnPCx": ("bit", 0x34, 1, 1, 5, 0),
    "EnableNightlightOnPA6": ("bit", 0x34, 1, 1, 6, 0),
})
STYLE_LAYOUTS = MappingProxyType({
    "IndicatorFunction": ("int", 0x60, 8, 2, 4, 0),
    "PrimaryColour": ("int", 0x60, 8, 1, 3, 0),
})
STYLES = MappingProxyType({"always_off": 0, "always_on": 1, "status_on": 2, "status_dual": 3})
COLOURS = MappingProxyType({"blue": 0, "orange": 1})
BRIGHTNESS_SOURCES = ("fixed", "group", "first_block")


def percent_to_brightness(percent: int) -> int:
    """PercentToLevel then IndicatorBrightnessLevelToLevel (Toolkit integer maths)."""
    level = percent * 255 // 100
    # Sequential remaps keep a fixed level out of the $00..$03 source codes.
    if level == 5:
        level = 6
    if level == 2:
        level = 5
    if level == 0:
        level = 4
    return level


def brightness_to_percent(value: int) -> int | None:
    """Slider position Toolkit shows for a fixed-level byte, if one maps to it."""
    return next((percent for percent in range(101) if percent_to_brightness(percent) == value), None)


def _profile(spec, allowed, label):
    profile = PROFILES.get(spec.filename)
    if profile is None or profile[0] != spec.unit_type:
        raise PPEditError(label + " supports the admitted Neo-core profiles only")
    family = FAMILIES[spec.unit_type]
    if family not in allowed:
        raise PPEditError(f"Toolkit's {label} wizard excludes {family} Neo units ({spec.unit_type})")
    return family


class NeoIndicatorOptions(PPEditor):
    FORMAT = "cbus-neo-indicator-options-plan-v1"

    def __init__(self, spec):
        # TUnitMagicNeoIndicatorOptions.IsUnitEligible excludes TCBusNeoProClassicInputUnit.
        self.family = _profile(spec, ("standard", "saturn", "reflection"), "Indicator Options")
        super().__init__(spec, spec.unit_type, OPTION_LAYOUTS)
        self.nightlight_parameter = "EnableNightlightOnPA6" if self.family == "standard" else "EnableNightlightOnPCx"

    def plan(self, current, *, brightness=None, brightness_percent=None, brightness_group=None,
             key_press_level=None, key_press_seconds=None, nightlight=None, ignore_first_key_press=None,
             timer_flash=None, id_backlight=None):
        original = self.snapshot(current)
        updates = {name: list(values) for name, values in original.items()}
        details = {"family": self.family}
        if brightness is not None:
            if brightness not in BRIGHTNESS_SOURCES:
                raise PPEditError("Brightness source must be fixed, group or first_block")
            if brightness == "fixed":
                percent = integer(brightness_percent, "Brightness percent") if brightness_percent is not None else None
                if percent is None or not 0 <= percent <= 100 or brightness_group is not None:
                    raise PPEditError("A fixed level needs brightness_percent 0..100 and no group")
                updates["IndicatorBrightness"] = [percent_to_brightness(percent)]
            elif brightness == "group":
                group = integer(brightness_group, "Brightness group") if brightness_group is not None else None
                if group is None or not 0 <= group <= 255 or brightness_percent is not None:
                    raise PPEditError("Level of group needs brightness_group 0..255 (255 = unused) and no percent")
                updates["IndicatorBrightness"] = [0]
                updates["GroupAddress"][8] = group
            else:
                if brightness_percent is not None or brightness_group is not None:
                    raise PPEditError("Level of first block takes no percent or group")
                updates["IndicatorBrightness"] = [1]
        elif brightness_percent is not None or brightness_group is not None:
            raise PPEditError("Select a brightness source")
        if key_press_seconds is not None:
            seconds = integer(key_press_seconds, "Key-press duration")
            if not 0 <= seconds <= 15:
                raise PPEditError("Key-press duration is 1..15 seconds, or 0 to disable brightening")
            updates["TimerDuration"] = [seconds]
            if seconds and key_press_level is None:
                raise PPEditError("Enabling key-press brightening needs key_press_level 0..15")
        if key_press_level is not None:
            level = integer(key_press_level, "Key-press level")
            if not 0 <= level <= 15:
                raise PPEditError("Key-press level is 0..15")
            if updates["TimerDuration"][0] == 0:
                raise PPEditError("Toolkit sets the key-press level only with a 1..15 second duration")
            updates["IndicatorPressedLevel"] = [level]
        for name, value, label in ((self.nightlight_parameter, nightlight, "nightlight"),
                                   ("FirstKeyThrowAway", ignore_first_key_press, "ignore_first_key_press"),
                                   ("IDBacklightIllumination", id_backlight, "id_backlight")):
            if value is not None:
                updates[name] = [int(boolean(value, label))]
        if timer_flash is not None:
            updates["DisableTimerFlash"] = [int(not boolean(timer_flash, "timer_flash"))]
        if nightlight is not None:
            # The agent always writes EnableNightlight false and clears the
            # nightlight bit this family does not use.
            updates["EnableNightlight"] = [0]
            other = "EnableNightlightOnPCx" if self.nightlight_parameter == "EnableNightlightOnPA6" else "EnableNightlightOnPA6"
            updates[other] = [0]
        # UpdateKeyPressUI: nightlight needs key-press brightening, and
        # ignoring the first press needs the nightlight.
        if any(value is not None for value in (nightlight, ignore_first_key_press, key_press_seconds)):
            if updates[self.nightlight_parameter][0] and not updates["TimerDuration"][0]:
                raise PPEditError("Toolkit enables the nightlight only with key-press brightening")
            if updates["FirstKeyThrowAway"][0] and not updates[self.nightlight_parameter][0]:
                raise PPEditError("Toolkit ignores the first key press only with the nightlight enabled")
        value = updates["IndicatorBrightness"][0]
        details["brightness"] = {"source": "group" if value == 0 else "first_block" if value <= 3 else "fixed",
                                 "percent": brightness_to_percent(value) if value > 3 else None,
                                 "group": updates["GroupAddress"][8] if value == 0 else None}
        details["nightlight_parameter"] = self.nightlight_parameter
        return self.make_plan(original, updates, details)

    def configure(self, session, **options):
        return self.apply(session, self.plan(session.values(), **options))


class NeoIndicatorStyles(PPEditor):
    FORMAT = "cbus-neo-indicator-styles-plan-v1"

    def __init__(self, spec):
        # TUnitMagicNeoLED.IsUnitEligible excludes Classic and Reflection Neo
        # classes; IndicatorFunction follows Neo4IndicatorFunction only for
        # IsNeoStandard, IsNeoSaturn and IsNeoBC classes.
        self.family = _profile(spec, ("standard", "saturn"), "Indicator Styles and Colours")
        super().__init__(spec, spec.unit_type, STYLE_LAYOUTS)

    def plan(self, current, *, colour, style=None):
        if colour not in COLOURS:
            raise PPEditError("Colour must be blue or orange")
        if style is not None and style not in STYLES:
            raise PPEditError("Style must be always_off, always_on, status_on or status_dual")
        original = self.snapshot(current)
        count = len(original["PrimaryColour"])
        updates = dict(original, PrimaryColour=(COLOURS[colour],) * count)
        if style is not None:
            updates["IndicatorFunction"] = (STYLES[style],) * count
        details = {"family": self.family, "colour": colour, "style": style,
                   "off_colour": ("orange" if colour == "blue" else "blue") if style in (None, "status_dual") else None,
                   "avanti_colour_note": self.unit_type in AVANTI}
        return self.make_plan(original, updates, details)

    def configure(self, session, **options):
        return self.apply(session, self.plan(session.values(), **options))
