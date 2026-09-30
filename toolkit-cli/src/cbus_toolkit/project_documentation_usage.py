"""Source-pinned group and ActionSelectorUse descriptions for bounded unit families.

These helpers reproduce the native description strings, not an original generated
page. Missing consumed PP data is explicit; an empty recovered description means
that the original method has no use to report. No missing values are guessed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .din_output_settings import PROFILES
from .macros import STAGES, SUPPORTED_UNITS
from .project_documentation_outputs import output_profile

CLASSIC_OUTPUT_CHANNELS = {"RELAY1": 1, "RELAY2": 2, "RELAY4": 4, "DIMMER4": 4, "AN_OUT4": 4}
DIRECT_ACTIONS = {
    "FanController": ("RELDF1", "FanTriggerGroup", "FanActionSelector", "Fan Speed Cycle"),
    "SENTEMPPro": ("SENTEMPB", "BroadcastTriggerGroup", "BroadcastTriggerLevel", "Trigger Temperature Broadcast"),
}
DIGITAL_ACTIONS = (
    ("ErrorReportingTriggerGroup", "ErrorReportingActionSelector", "Trigger Error Report"),
    ("BroadcastTriggerGroup", "BroadcastActionSelector", "Trigger Temperature Report"),
)
DIGITAL_CHANNEL_COUNT = 4
NO_INDICATOR_BRIGHTNESS = frozenset({"KEYBC2", "KEYBC4", "KEYAUX4", "DINAUX4"})
GROUP_LABELS = ("Channel %d", "Logic Group", "Logic Group (Unused)", "Key %d", "Block (Unused)",
                "Area Group", "Indicator Brightness Group")


class UnitSnapshot(Protocol):
    unit_type: str
    parameters: dict[str, str]

    def array(self, name: str) -> list[int] | None: ...


@dataclass(frozen=True)
class Usage:
    html: str = ""
    status: str = "recovered"
    missing: tuple[str, ...] = ()


def _missing(*names: str) -> Usage:
    return Usage(status="unrecovered", missing=tuple(names))


def _array(unit: UnitSnapshot, name: str, count: int, maximum: int = 255) -> list[int] | None:
    values = unit.array(name)
    if values is None or len(values) < count or any(not 0 <= n <= maximum for n in values):
        return None
    return values


def _application(unit: UnitSnapshot) -> int | None:
    values = _array(unit, "Application", 1)
    return values[0] if values else None


def _joined(items: list[str]) -> Usage:
    # Native per-unit methods append a trailing '|'. InsertHTMLGroup* removes
    # precisely the final character, then replaces every remaining | with <br/>.
    return Usage("<br/>".join(items))


def group_usage(unit: UnitSnapshot, application: int, group: int, kind: str) -> Usage:
    """Describe one unit in an Input/Output/Other group section, in native order."""
    if kind not in {"input", "output", "other"}:
        raise ValueError("Group usage kind must be input, output or other")
    typ = unit.unit_type.upper()
    if typ == "SENTEMP4":
        return _digital_group_usage(unit, application, group, kind)
    if typ == "RELDF1":
        if kind == "other":
            return Usage()  # TCBusDimmerUnit's base-only override.
        if kind == "input":
            trigger = _array(unit, "FanTriggerGroup", 1)
            if trigger is None:
                return _missing("FanTriggerGroup")
            if trigger[0] == 255:
                return Usage()
            primary = _application(unit)
            if primary is None:
                return _missing("Application")
            if primary != application:
                return Usage()
            groups = _array(unit, "GroupAddress", 1)
            return (_missing("GroupAddress") if groups is None else
                    Usage("Fan Speed Cycle" if groups[0] == group else ""))
    classic = typ in CLASSIC_OUTPUT_CHANNELS
    profile = output_profile(unit)
    din = profile is not None
    keys = typ in SUPPORTED_UNITS
    if not (classic or din or keys):
        return _missing("unit group dependency implementation")
    if ((classic or din) and kind == "input") or (din and kind == "other") or (keys and kind == "output"):
        return Usage()  # Effective native base VMT method, or DIN's base-only wrapper.
    primary = _application(unit)
    if primary is None:
        return _missing("Application")
    if primary != application:
        return Usage()
    if kind == "other":
        area = _array(unit, "AreaGroupAddress", 1)
        missing, descriptions = [], []
        if area is None:
            missing.append("AreaGroupAddress")
        elif area[0] == group:
            descriptions.append("Area Group")
        if keys and typ not in NO_INDICATOR_BRIGHTNESS:
            brightness = unit.parameters.get("IndicatorBrightness")
            if brightness is None:
                missing.append("IndicatorBrightness")
            elif brightness.strip():
                # GetIndicatorBrightness creates this group whenever the PP
                # brightness string is nonempty, even for fixed brightness.
                groups = _array(unit, "GroupAddress", 5)
                if groups is None:
                    missing.append("GroupAddress")
                elif groups[4] == group:
                    descriptions.append("Indicator Brightness Group")
        return Usage("<br/>".join(descriptions), "partial" if missing else "recovered", tuple(missing))
    if keys:
        groups = _array(unit, "GroupAddress", 4)
        masks = _array(unit, "BlockAllocation", SUPPORTED_UNITS[typ])
        stages = [_array(unit, stage, SUPPORTED_UNITS[typ], 15) for stage in STAGES]
        missing = [name for name, value in zip(("GroupAddress", "BlockAllocation", *STAGES),
                                             (groups, masks, *stages)) if value is None]
        if missing:
            return _missing(*missing)
        descriptions = []
        for block in range(4):
            if groups[block] != group:
                continue
            matches = [f"Key {key + 1}" for key in range(SUPPORTED_UNITS[typ])
                       if masks[key] & (1 << block) and any(stage[key] for stage in stages)]
            descriptions.extend(matches or ["Block (Unused)"])
        return _joined(descriptions)
    indices = tuple(range(CLASSIC_OUTPUT_CHANNELS[typ])) if classic else profile.indices
    groups = _array(unit, "GroupAddress", 6 if classic else 16)
    logic_start, logic_count = (0, 6) if classic else (12, 4)
    if groups is None:
        return _missing("GroupAddress")
    descriptions, missing = [], []
    if din:
        descriptions.extend(f"Channel {channel}" for channel, index in enumerate(indices, 1)
                            if groups[index] == group)
    for logic in range(logic_count):
        if groups[logic_start + logic] != group:
            continue
        name = f"LogicGA{logic if classic else 13 + logic}Associations"
        associations = _array(unit, name, max(indices) + 1, 1)
        if associations is None:
            missing.append(name)
        else:
            descriptions.append("Logic Group" if any(associations[index] for index in indices)
                                else "Logic Group (Unused)")
    return Usage("<br/>".join(descriptions), "partial" if missing else "recovered", tuple(missing))


def _digital_group_usage(unit: UnitSnapshot, application: int, group: int, kind: str) -> Usage:
    if kind != "other" or application not in (172, 203):
        return Usage()
    if application == 203:
        enable = _array(unit, "ErrorReportingEnableGroup", 1)
        return (_missing("ErrorReportingEnableGroup") if enable is None else
                Usage("Error Report Enable Group" if enable[0] == group else ""))
    descriptions, missing = [], []
    for channel in range(1, DIGITAL_CHANNEL_COUNT + 1):
        prefix = f"Channel{channel}"
        mode = _array(unit, prefix + "ChannelMode", 1)
        if mode is None:
            missing.append(prefix + "ChannelMode")
        elif mode[0] == 172:
            communication = _array(unit, prefix + "HVACCommunicationGroup", 1)
            if communication is None:
                missing.append(prefix + "HVACCommunicationGroup")
            elif communication[0] == group:
                descriptions.append(f"Communication Group Channel {channel}")
        # Other channel modes load the AC application's unused (255) group.
        elif group == 255:
            descriptions.append(f"Communication Group Channel {channel}")
    return Usage("<br/>".join(descriptions), "partial" if missing else "recovered", tuple(missing))


def _selector_match(unit: UnitSnapshot, application: int, group: int, address: int,
                    group_parameter: str, selector_parameter: str) -> tuple[bool | None, tuple[str, ...]]:
    if application != 202:
        return False, ()
    trigger = _array(unit, group_parameter, 1)
    if trigger is None:
        return None, (group_parameter,)
    if trigger[0] == 255 or trigger[0] != group:
        return False, ()
    selector = _array(unit, selector_parameter, 1)
    return (None, (selector_parameter,)) if selector is None else (selector[0] == address, ())


def action_selector_usage(unit: UnitSnapshot, action_documentor: str, application: int, group: int,
                          address: int, value: int) -> Usage:
    """Reproduce admitted ActionSelectorUse methods, retaining their native quirks."""
    if action_documentor == "UnitType":
        return Usage()
    typ = unit.unit_type.upper()
    if action_documentor in DIRECT_ACTIONS and typ == DIRECT_ACTIONS[action_documentor][0]:
        _, group_parameter, selector_parameter, label = DIRECT_ACTIONS[action_documentor]
        matches, missing = _selector_match(unit, application, group, address, group_parameter, selector_parameter)
        return _missing(*missing) if missing else Usage("<li />" + label if matches else "")
    if action_documentor == "DigitalTemperatureSensor" and typ == "SENTEMP4":
        matches = [_selector_match(unit, application, group, address, group_parameter, selector_parameter)
                   for group_parameter, selector_parameter, _ in DIGITAL_ACTIONS]
        # Native UStrCat3 replaces the result in both branches. A known broadcast
        # match determines the final output even when the earlier error use is unknown.
        if matches[1][0]:
            return Usage("<li />" + DIGITAL_ACTIONS[1][2])
        missing = tuple(name for _, names in matches for name in names)
        if missing:
            return _missing(*missing)
        return Usage("<li />" + DIGITAL_ACTIONS[0][2] if matches[0][0] else "")
    if action_documentor != "ClassicKeyInput" or typ not in SUPPORTED_UNITS:
        return _missing("ActionSelectorUse implementation")
    primary = _application(unit)
    if primary is None:
        return _missing("Application")
    if primary != application:
        return Usage()
    names = ("GroupAddress", "BlockAllocation", "LightLevelStore1", "LightLevelStore2",
             "TimerExpiryCommand", *STAGES)
    counts = (4, SUPPORTED_UNITS[typ], 4, 4, 4, *([SUPPORTED_UNITS[typ]] * 4))
    arrays = [_array(unit, name, count, 15 if name in (*STAGES, "TimerExpiryCommand") else 255)
              for name, count in zip(names, counts)]
    missing = [name for name, values in zip(names, arrays) if values is None]
    if missing:
        return _missing(*missing)
    groups, masks, stored1, stored2, expiry, *stages = arrays
    descriptions = []
    for key in range(SUPPORTED_UNITS[typ]):
        commands = {stage[key] for stage in stages}
        for block in range(4):
            if not masks[key] & (1 << block) or groups[block] != group or stored1[block] != address:
                continue
            if 12 in commands or (7 in commands and expiry[block] == 12):
                descriptions.append(f"Key {key + 1}")
            # The original does not independently test stored2. Address and Value
            # are distinct native Level properties; do not normalize either.
            if stored2[block] == value and (6 in commands or (7 in commands and expiry[block] == 6)):
                descriptions.append(f"Key {key + 1}")
    return _joined(descriptions)
