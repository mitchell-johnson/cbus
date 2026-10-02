"""Source-recovered conversion into a fresh classic DLT model.

This is the DynamicLabel agent's own hook, which does not call the inherited
Learn/CoreKey/NeoPro conversion hooks. Evidence comes from static reads of the
pinned Toolkit 1.18 EXE/MAP, not execution of the original application.
"""
from __future__ import annotations

import re

from .toolkit_conversion_key_to_neo import CLASSIC_ATTRIBUTES, CLASSIC_TYPES, NEOPRO_ATTRIBUTES
from .unitspec import UnitSpec

TWEAKERS = frozenset(("TTweakerDLT", "TTweakerKeyToDLT"))
DLT_TYPES = ("KEYDL4", "KEYML5", "KEYBL5")
MODERN_TYPES = tuple("KEYM2 KEYM4 KEYM8 KEYB2 KEYB4 KEYB6 KEYH1 KEYH2 KEYH3 KEYH4 "
                     "KEYA1 KEYA3 KEYA6 KEYA8 KEYAV2 KEYAV4 "
                     "KEYCIR1 KEYCIR4 KEYC1 KEYC2 KEYC4 KEYE1 KEYE2 KEYE3 KEYE4 "
                     "KEYP2 KEYP4 KEYP6 KEYEIR1 KEYEIR2 KEYEIR3 KEYEIR4".split())
STANDARD_TYPES = frozenset(("KEYM2", "KEYM4", "KEYM8"))
NEO_CLASSIC_TYPES = frozenset(("KEYC1", "KEYC2", "KEYC4", "KEYCIR1", "KEYCIR4"))
KEYE_TYPES = frozenset(t for t in MODERN_TYPES if t.startswith("KEYE"))
TARGET_FIRMWARE = "2.1.00"
MISSING_FACTORY = "KEYM6 has no recovered static Toolkit unit factory/model; its DLT registrations remain refused"
MISSING_SPECIFICATION = "KEYBIR source specification identity or catalogue alias is not established for the recovered DLT profile"

# InternalCreate calls CoreNeoPro directly, not the NeoPro constructor which
# adds NightlightColour. Add appends rather than replacing same-named fields:
# the two KeyDisable attributes occur twice in the original PP SET order.
DLT_ATTRIBUTES = NEOPRO_ATTRIBUTES[:-1] + tuple((name, True) for name in (
    "EnablePageFallback", "EnableIndicatorPressedLevel", "EnableNightlightOnToggleKey",
    "EnableNightlightOnUserKeys", "IndicatorMode", "DisableKeySlider", "InvertDisplay",
    "HideClock", "EnableScheduling", "EnableSceneToggle", "EnableDynamicLabels",
    "EEPROMChecksumAlarm", "KeyDisableGroup", "KeyDisableGroupInvert", "LabelFlavourLSB",
    "LabelFlavourMSB", "LCDMFirmwareVersion", "LCDMVocabularyVersion"))
ATTRIBUTES = {**{t: CLASSIC_ATTRIBUTES for t in CLASSIC_TYPES},
              **{t: NEOPRO_ATTRIBUTES + (("KeyMask", True),) if t in KEYE_TYPES else NEOPRO_ATTRIBUTES
                 for t in MODERN_TYPES}, **{t: DLT_ATTRIBUTES for t in DLT_TYPES}}
IMMUTABLE = ("IRBank", "IDBacklightIllumination", "PrimaryColour", "EnableNightlight",
             "EnableNightlightOnPCx", "EnableNightlightOnPA6", "DisableIR", "DisableIRNEC")
CLASSIC_IMMUTABLE = ("ControlAppGroupAddress", "PatchEnable", "SceneKeySelector", "SceneTable", "SceneTablePointer")


def source_firmware(unit_type):
    kind = unit_type.upper()
    if kind in CLASSIC_TYPES:
        return "1.2.67"
    if kind in MODERN_TYPES:
        return "2.5.00"
    if kind in DLT_TYPES:
        return TARGET_FIRMWARE
    raise ValueError("No recovered DLT source model for " + kind)


def require_target_firmware(value):
    if value != TARGET_FIRMWARE:
        raise ValueError("DLT conversion requires a fresh target at firmware 2.1.00")


def specification(unit_type):
    kind = unit_type.upper()
    if kind in ("KEYBL5", "KEYML5"):
        return "KEYL5.xml", "KEYL5"
    if kind == "KEYDL4":
        return "KEYL4.xml", "KEYDL4"
    if kind in KEYE_TYPES:
        return "KEYE.xml", "KEYE1"
    return kind + ".xml", kind


def validate_spec(unit_type, spec, *, source):
    kind = unit_type.upper()
    filename, declared_type = specification(kind)
    firmware = source_firmware(kind) if source else TARGET_FIRMWARE
    if (not isinstance(spec, UnitSpec) or spec.filename != filename
            or spec.unit_type.upper() != declared_type or not spec.supports_version(firmware)):
        raise ValueError("DLT conversion requires the matching source-pinned specification and firmware")
    classic = kind in CLASSIC_TYPES
    shape = {"Application": ("int", 2, 8), "GroupAddress": ("int", 8 if classic else 9, 8),
             "IndicatorFunction": ("int", 4 if classic else 8, 2), "IndicatorBrightness": ("int", 1, 8),
             **{name: ("bit", 1, 8) for name in ("LearnMode", "LearnAnyApp", "LearnedFlag")}}
    if not classic:
        shape["FirstKeyThrowAway"] = ("bit", 1, 8)
        if kind not in DLT_TYPES:
            shape.update({name: ("bit", 1, 8) for name in ("EnableNightlightOnPCx", "EnableNightlightOnPA6")})
    if kind in DLT_TYPES:
        for name in ("EnableNightlightOnPCx", "EnableNightlightOnPA6"):
            if name in spec.parameters:
                raise ValueError("Unsupported DLT source model PP field " + name)
        shape.update({"EnablePageFallback": ("bit", 1, 8), "IndicatorMode": ("int", 1, 2),
                      **{name: ("bit", 1, 8) for name in ("EnableNightlightOnToggleKey", "EnableNightlightOnUserKeys")},
                      "LabelFlavourLSB": ("int", 8, 1), "LabelFlavourMSB": ("int", 8, 1)})
    for name, expected in shape.items():
        parameter = spec.parameters.get(name)
        if parameter is None or (parameter.type, parameter.array_size, parameter.bit_size) != expected:
            raise ValueError("Unsupported DLT conversion PP shape for " + name)


def _numbers(value, name, maximum):
    result = []
    for token in str(value).split():
        if not re.fullmatch(r"\+?(?:\$[0-9A-Fa-f]+|0[xX][0-9A-Fa-f]+|[0-9]+)", token):
            raise ValueError("Invalid DLT source " + name)
        token = token.lstrip("+")
        number = int(token[1:] if token.startswith("$") else token,
                     16 if token.startswith("$") or token.lower().startswith("0x") else 10)
        if not 0 <= number <= maximum:
            raise ValueError("Invalid DLT source " + name)
        result.append(number)
    return result


def _scalar(source, name, maximum=1):
    values = _numbers(source.get(name, ""), name, maximum)
    if len(values) > 1:
        raise ValueError("Invalid DLT source scalar " + name)
    return values[0] if values else 0


def apply_hooks(source_type, source_values, values, mutable, origin, not_written):
    """TweakParameters followed by the DLT-only BeforeUnitConversionSave."""
    kind = source_type.upper()
    classic = kind in CLASSIC_TYPES
    for name in IMMUTABLE + (CLASSIC_IMMUTABLE if classic else ()):
        mutable[name] = False
        not_written[name] = "DLT tweaker retains the fresh target default"
    for name in ("LabelFlavourLSB", "LabelFlavourMSB"):
        values[name], origin[name] = "0", "DLT literal (one PP array element)"
        if mutable[name]:
            not_written.pop(name, None)
    if classic and "IndicatorFunction" in values and values["IndicatorFunction"]:
        numbers = _numbers(values["IndicatorFunction"], "IndicatorFunction", 3)
        values["IndicatorFunction"] = "".join(str({1: 2, 3: 1}.get(n, n)) + " " for n in numbers)
        origin["IndicatorFunction"] = "classic indicator remap 1->2, 3->1"
    if kind not in DLT_TYPES:
        for name in ("EnablePageFallback", "IndicatorMode"):
            mutable[name] = False
            not_written[name] = "DLT hook suppresses this field for a non-DLT source"
    if classic:
        return
    # Neo source model loading uses PA6 only for Neo Standard, PCx otherwise;
    # Neo Classic disables nightlight and first-key throw-away in its model.
    nightlight = 0 if kind in NEO_CLASSIC_TYPES else _scalar(
        source_values, "EnableNightlightOnPA6" if kind in STANDARD_TYPES else "EnableNightlightOnPCx")
    first_key = 0 if kind in NEO_CLASSIC_TYPES else _scalar(source_values, "FirstKeyThrowAway")
    brightness = _scalar(source_values, "IndicatorBrightness", 255)
    if kind not in NEO_CLASSIC_TYPES and brightness in (2, 3):
        brightness = 1
    elif kind in NEO_CLASSIC_TYPES and brightness == 2:
        brightness = 5
    for name, value in (("EnableNightlightOnToggleKey", nightlight), ("EnableNightlightOnUserKeys", nightlight),
                        ("FirstKeyThrowAway", first_key), ("IndicatorBrightness", brightness)):
        values[name], origin[name] = str(value), "DLT hook reads the loaded source Neo model"
        if name == "IndicatorBrightness":
            mutable[name] = True
        if mutable[name]:
            not_written.pop(name, None)


def context(source_type):
    kind = source_type.upper()
    return {"profile": "source-pinned-to-fresh-dlt-2.1.00", "source_firmware": source_firmware(kind),
            "target_firmware": TARGET_FIRMWARE, "fresh_target_model": True,
            "source_is_neo": kind not in CLASSIC_TYPES, "source_is_dlt": kind in DLT_TYPES,
            "source_is_neo_classic": kind in NEO_CLASSIC_TYPES, "source_is_neo_standard": kind in STANDARD_TYPES,
            "inherited_conversion_hooks_called": False, "target_programming_loaded_before_hook": False}
