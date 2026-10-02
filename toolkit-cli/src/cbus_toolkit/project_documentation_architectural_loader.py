"""Fresh TDIMARX snapshot projection from explicit consumed programming data.

The original loader uses 128 sparse scene slots. Its ordinary SceneGroups are
prepared once, in channel order; its special SceneGroups remain empty. This
module preserves that lifecycle and never invents absent native objects.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from .project_documentation_devices import _required_array
from .project_documentation_outputs import _registration

PROFILES = {"DIMAR3": ("TDIMAR3", 3), "DIMAR6": ("TDIMAR6", 6),
            "DIMAR12": ("TDIMAR12", 12), "C12DIMAR": ("TDIMAR12", 12)}
CURVES = ("Fan Control", "Linear (1:1)", "Tungsten", "Tungsten-Halogen", "Neon",
          "Square Law", "S Curve", "Linear Power", "Switch", "Dimming Curve A", "Dimming Curve B")
RAMPS = ("Instant", "4 secs", "8 secs", "12 secs", "20 secs", "30 secs", "40 secs", "60 secs",
         "90 secs", "120 secs", "180 secs", "300 secs", "420 secs", "600 secs", "900 secs", "1020 secs")
# Fixed constructor cache: (normalised RMS voltage, level). Editable curve A/B
# points are independent objects, and are not used by this report conversion.
RMS_A = ((55,25),(60,29),(64,33),(69,36),(73,41),(78,44),(83,48),(88,52),(92,56),
         (97,60),(102,64),(107,68),(112,73),(117,76),(121,81),(126,84),(131,88),
         (136,93),(140,96),(145,101),(149,104),(154,108),(158,111),(163,115),
         (167,119),(171,123),(175,126),(180,129),(184,133),(187,136),(191,139),
         (195,143),(199,145),(202,148),(207,153),(213,159),(221,166),(228,176),
         (236,185),(239,190),(253,230),(255,255))
SPECIAL_FIELDS = ("SceneDryContact1", "SceneDryContact2", "SceneDryContact3", "SceneLoadShed", "SceneCBusLoss")
SCENE_SLOTS = 128


def architectural_profile(unit):
    row = _registration(unit)
    profile = PROFILES.get(unit.unit_type.upper())
    if row is None or profile is None or row[3:5] != (profile[0], "TDIMARXCGateAgent"):
        raise ValueError("unrecovered architectural dimmer class or firmware")
    return profile[1]


def _byte(unit, name):
    return _required_array(unit, name, 1)[0]


def _word(unit, name):
    return _required_array(unit, name, 1, 65535)[0]


def _bits(unit, name, count):
    # StrToBoolArray calls StrToIntDef, then IntToBool(nonzero). A stored byte
    # need not be the canonical 1 to enable a flag.
    return tuple(bool(n) for n in _required_array(unit, name, count))


def percent(level):
    return (level + 2) * 100 // 255


def scene_level(raw):
    """The loader scales 254 to 255 before the report's percentage conversion."""
    if not 0 <= raw <= 255:
        raise ValueError("architectural scene target outside byte range")
    return min(255, round(Fraction(raw * 255, 254)))


def rms_voltage(level, line_voltage):
    """Original fixed-cache interpolation ROUND, then truncating integer scaling."""
    if not 0 <= level <= 255 or not 0 <= line_voltage <= 65535:
        raise ValueError("architectural voltage input outside admitted byte/word range")
    previous_x = previous_y = result = 0
    for x, y in RMS_A:
        if y == level:
            result = x
            break
        result = round(Fraction((x - previous_x) * (level - previous_y), y - previous_y) + previous_x)
        if y > level:
            break
        previous_x, previous_y = x, y
    return line_voltage * result // 255


def cross_fade_parts(word):
    if not 0 <= word <= 65535:
        raise ValueError("architectural fade word outside 0..65535")
    seconds = (word & 0x3fff) * (1, 10, 60, 0)[word >> 14]
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return days, hours, minutes, seconds


@dataclass(frozen=True)
class SceneChannel:
    channel: int
    group: int
    fade: int
    target: int
    inhibit: int


@dataclass(frozen=True)
class Scene:
    slot: int
    name: str
    trigger: int
    selector: int | None
    cross_fade: bool
    fade: int
    use_ramp: bool
    channels: tuple[SceneChannel, ...]
    groups: tuple[SceneChannel, ...]


def _utf16_prefix(text, units):
    # Delphi Copy counts UTF-16 units. Do not invent an original UTF-8 encoder's
    # replacement behavior when that prefix ends in a split surrogate.
    try:
        return text.encode("utf-16le")[:units * 2].decode("utf-16le")
    except UnicodeError as error:
        raise ValueError("SceneNNNName (unrecovered split-surrogate UTF-8 conversion)") from error


def architectural_scenes(unit, *, count=None, output_groups=None):
    count = architectural_profile(unit) if count is None else count
    groups = _required_array(unit, "GroupAddress", 16)[:count] if output_groups is None else output_groups
    used = _bits(unit, "SceneUsed", SCENE_SLOTS)
    if not any(used):
        return ()
    named = _bits(unit, "SceneHasName", SCENE_SLOTS)
    normal = _bits(unit, "SceneNormal", SCENE_SLOTS)
    ramp = _bits(unit, "SceneUsesRampRate", SCENE_SLOTS)
    scenes = []
    for slot, enabled in enumerate(used, 1):
        if not enabled:
            continue
        name = "New Scene"
        if named[slot - 1]:
            field = f"Scene{slot:03d}Name"
            if field not in unit.parameters:
                raise ValueError(field + " (requires explicit scene name)")
            name = _utf16_prefix(unit.parameters[field].strip(''.join(map(chr, range(33)))), 38)
        raw = _required_array(unit, f"Scene{slot:03d}Data", 2 + count * 4)
        channels, unique, seen = [], [], set()
        for index in range(count):
            low, high, target, flags = raw[2 + index * 4:6 + index * 4]
            if flags & 8:
                continue
            channel = SceneChannel(index, groups[index], low + high * 256, scene_level(target), flags & 7)
            channels.append(channel)
            if channel.group not in seen:
                seen.add(channel.group)
                unique.append(channel)
        scenes.append(Scene(slot, name, raw[0], None if raw[0] == 255 else raw[1],
                            not normal[slot - 1], raw[2] + raw[3] * 256, ramp[slot - 1],
                            tuple(channels), tuple(unique)))
    return tuple(scenes)


def architectural_data(unit):
    count = architectural_profile(unit)
    groups = _required_array(unit, "GroupAddress", 16)
    curves = tuple(value if value <= 10 else 1 for value in _required_array(unit, "DimmingCurve", count))
    data = {"count": count, "application": _byte(unit, "Application"), "groups": tuple(groups[:count]),
            "logic": tuple(groups[12:16]), "curves": curves,
            "associations": tuple(tuple(bool(n) for n in _required_array(unit, f"LogicGA{13 + index}Associations", count))
                                  for index in range(4)),
            "functions": tuple(_required_array(unit, "LogicFunction", count)),
            "minimum": tuple(_required_array(unit, "MinDimmingLevel", count)),
            "maximum": tuple(_required_array(unit, "MaxDimmingLevel", count)),
            "max_voltage": tuple(_required_array(unit, "ChannelMaxLevelA", count)),
            "line_voltage": _required_array(unit, "NominalLineVoltage", 1, 65535)[0],
            "threshold": tuple(_required_array(unit, "TurnOnThreshold", count)),
            "enable": _byte(unit, "ChannelEnableGroup"), "dmx_enable": _byte(unit, "DMXEnableGroup")}
    data["kickstart"] = tuple(_required_array(unit, "FanKickstartTime", count, 65535)) if 0 in curves else ()
    data["cbus_masks"] = (tuple(tuple(not n for n in _bits(unit, f"ChannelMask{index}", count))
                                for index in range(1, 5)) if data["enable"] != 255 else ())
    patches = _required_array(unit, "DMXChannelMapping", count * 2)
    current = _bits(unit, "DMXChannelMaskCurrent", count) if data["dmx_enable"] == 255 else (True,) * count
    data["dmx"] = tuple((patches[index * 2] + 256 * patches[index * 2 + 1]) if current[index] else 0 for index in range(count))
    if data["dmx_enable"] != 255:
        data["dmx_masks"] = tuple(_bits(unit, f"DMXChannelMask{index}", count) for index in range(1, 5))
        data["dmx_on"] = tuple(_required_array(unit, "DMXOnFadeTime", count, 65535))
        data["dmx_take"] = _bits(unit, "DMXDisableOperation", count)
        data["dmx_off"] = tuple(_required_array(unit, "DMXOffFadeTime", count, 65535)) if any(data["dmx_take"]) else ()
        data["dmx_ramp"] = tuple(_required_array(unit, "DMXDisableRampRate", count)) if not all(data["dmx_take"]) else ()
        if any(data["dmx_ramp"][index] >= len(RAMPS) for index, take in enumerate(data["dmx_take"]) if not take):
            raise ValueError("DMXDisableRampRate (unrecovered enumerated ordinal)")
    data["special"] = {name: tuple((index, scene_level(raw)) for index, raw in enumerate(_required_array(unit, name, count))
                                   if raw != 255) for name in SPECIAL_FIELDS}
    data["loss_fade"] = _word(unit, "CBusLossFadeTime") if data["special"]["SceneCBusLoss"] else None
    data["halogen_mask"] = _bits(unit, "HalogenCleanChannelMask", count)
    trigger = _byte(unit, "HalogenCleanTriggerGroup")
    data["halogen"] = None if trigger == 255 else (trigger, _byte(unit, "HalogenCleanActionSelector"))
    if data["halogen"] is not None and any(data["halogen_mask"]):
        data["halogen_fade"] = _word(unit, "HalogenFadeOn")
        data["halogen_duration"] = _word(unit, "HalogenCleanDuration")
    data["scenes"] = architectural_scenes(unit, count=count, output_groups=data["groups"])
    if any(channel.fade >= len(RAMPS) for scene in data["scenes"] if not scene.cross_fade and scene.use_ramp
           for channel in scene.groups):
        raise ValueError("SceneNNNData (unrecovered ramp ordinal)")
    return data
