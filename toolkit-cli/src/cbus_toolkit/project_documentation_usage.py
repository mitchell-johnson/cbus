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
NO_INDICATOR_BRIGHTNESS = frozenset({"KEYBC2", "KEYBC4", "KEYAUX4", "DINAUX4", "BCNC4A", "BCNC4B"})
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


def _classic_usage_count(unit: UnitSnapshot) -> int | None:
    typ = unit.unit_type.upper()
    if typ in SUPPORTED_UNITS:
        return SUPPORTED_UNITS[typ]
    if typ in {"BCNC4A", "BCNC4B"}:
        from .project_documentation_classic_profiles import classic_profile
        try:
            return classic_profile(unit)[0]
        except ValueError:
            pass
    return None


def _joined(items: list[str]) -> Usage:
    # Native per-unit methods append a trailing '|'. InsertHTMLGroup* removes
    # precisely the final character, then replaces every remaining | with <br/>.
    return Usage("<br/>".join(items))


def group_usage(unit: UnitSnapshot, application: int, group: int, kind: str, *, network=None) -> Usage:
    """Describe one unit in an Input/Output/Other group section, in native order."""
    if kind not in {"input", "output", "other"}:
        raise ValueError("Group usage kind must be input, output or other")
    typ = unit.unit_type.upper()
    if typ == "DIMPR12":
        from .project_documentation_bytecraft_usage import bytecraft_group_usage
        return bytecraft_group_usage(unit, application, group, kind)
    if typ == "SCNCTL5":
        from .project_documentation_scene_controller import scene_controller_group_usage
        return scene_controller_group_usage(unit, application, group, kind)
    from .project_documentation import select_documentor
    documentor = select_documentor(typ, getattr(unit, "firmware", ""))
    if documentor == "Multisensor":
        from .project_documentation_multisensor import multisensor_group_usage
        return multisensor_group_usage(unit, application, group, kind)
    if documentor == "ArchitecturalDimmer":
        from .project_documentation_architectural_usage import architectural_group_usage
        return architectural_group_usage(unit, application, group, kind)
    if documentor == "Thermostat":
        from .project_documentation_thermostat import thermostat_group_usage
        return thermostat_group_usage(unit, application, group, kind, network=network)
    if documentor == "CBusWirelessInput":
        from .project_documentation_wireless_usage import wireless_group_usage
        return wireless_group_usage(unit, application, group, kind)
    if documentor in {"WirelessGateway", "WirelessGatewayAdvanced"}:
        from .project_documentation_wireless_usage import gateway_group_usage
        return gateway_group_usage(unit, application, group, kind)
    if documentor == "RemoteControl":
        from .project_documentation_wireless_usage import remote_group_usage
        return _missing("Network context") if network is None else remote_group_usage(network, unit, application, group, kind)
    if documentor in {"LightLevelSensor", "ST7LightLevelSensor"}:
        from .project_documentation_light_level import light_level_group_usage
        return light_level_group_usage(unit, application, group, kind)
    if documentor in {"DALI2B", "WHAA"}:
        from .project_documentation_gateways import gateway_group_usage
        return gateway_group_usage(unit, application, group, kind)
    from .project_documentation_neoclassic import NEOCLASSIC_TYPES
    if typ in NEOCLASSIC_TYPES:
        from .project_documentation_neoclassic_usage import neoclassic_group_usage
        return neoclassic_group_usage(unit, application, group, kind)
    if documentor in {"PIR", "ST7PIRSensor"}:
        from .project_documentation_pir import pir_group_usage
        return pir_group_usage(unit, application, group, kind)
    if documentor in {"NeoInput", "NeoProInput", "DLT"}:
        from .project_documentation_neo_usage import neo_group_usage
        profile = None
        if documentor == "DLT":
            from .project_documentation_dlt import dlt_profile
            try:
                profile = dlt_profile(unit)
            except ValueError as exc:
                return _missing(str(exc))
        return neo_group_usage(unit, application, group, kind, profile=profile, dlt=documentor == "DLT")
    if typ == "SENTEMP4":
        return _digital_group_usage(unit, application, group, kind)
    if typ in {"SENTEMP", "SENTEMPB"}:
        from .project_documentation_temperature import temperature_group_usage
        return temperature_group_usage(unit, application, group, kind)
    from .project_documentation_special_outputs import ERROR_CHANNELS, error_output_other_usage
    if typ in ERROR_CHANNELS and kind == "other":
        return error_output_other_usage(unit, application, group)
    if typ == "RELDF1":
        if kind == "output":
            from .project_documentation_special_outputs import fan_output_usage
            return fan_output_usage(unit, application, group)
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
    key_count = _classic_usage_count(unit)
    keys = key_count is not None
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
            elif brightness:
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
        masks = _array(unit, "BlockAllocation", key_count)
        stages = [_array(unit, stage, key_count, 15) for stage in STAGES]
        missing = [name for name, value in zip(("GroupAddress", "BlockAllocation", *STAGES),
                                             (groups, masks, *stages)) if value is None]
        if missing:
            return _missing(*missing)
        descriptions = []
        for block in range(4):
            if groups[block] != group:
                continue
            matches = [f"Key {key + 1}" for key in range(key_count)
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
                          address: int, value: int, *, network=None) -> Usage:
    """Reproduce admitted ActionSelectorUse methods, retaining their native quirks."""
    if action_documentor == "UnitType":
        return Usage()
    if action_documentor == "DALI2B":
        from .project_documentation_gateways import dali_action_selector_usage
        return dali_action_selector_usage(unit, application, group, address, value)
    if action_documentor == "ArchitecturalDimmer":
        from .project_documentation_architectural_usage import architectural_action_selector_usage
        return architectural_action_selector_usage(unit, application, group, address, value)
    if action_documentor == "CBusWirelessInput":
        from .project_documentation_wireless_usage import wireless_action_usage
        return wireless_action_usage(unit, application, group, address)
    if action_documentor == "WirelessGatewayAdvanced":
        from .project_documentation_wireless_usage import gateway_action_usage
        return _missing("Network context") if network is None else gateway_action_usage(network, unit, application, group, address)
    if action_documentor == "RemoteControl":
        from .project_documentation_wireless_usage import remote_action_usage
        return remote_action_usage(unit, application, group, address)
    if action_documentor == "ErrorReportOutput":
        from .project_documentation_special_outputs import error_output_action_usage
        return error_output_action_usage(unit, application, group, address, value)
    typ = unit.unit_type.upper()
    from .project_documentation_multisensor import TYPES as MULTISENSOR_TYPES, multisensor_action_selector_usage
    if typ in MULTISENSOR_TYPES and action_documentor == "NeoInput":
        return multisensor_action_selector_usage(unit, application, group, address, value)
    if action_documentor == "BytecraftDimmer" and typ == "DIMPR12":
        from .project_documentation_bytecraft_usage import bytecraft_action_selector_usage
        return bytecraft_action_selector_usage(unit, application, group, address, value)
    if action_documentor == "ClassicKeyInput":
        from .project_documentation_neoclassic import NEOCLASSIC_TYPES
        if typ in NEOCLASSIC_TYPES:
            from .project_documentation_neoclassic_usage import neoclassic_action_selector_usage
            return neoclassic_action_selector_usage(unit, application, group, address, value)
        from .project_documentation_pir import PIR_TYPES, pir_action_selector_usage
        if typ in PIR_TYPES:
            return pir_action_selector_usage(unit, application, group, address, value)
    if action_documentor == "CustomSceneController" and typ == "SCNCTL5":
        from .project_documentation_scene_controller import scene_controller_action_usage
        return scene_controller_action_usage(unit, application, group, address, value)
    if action_documentor in {"NeoInput", "NeoProInput"}:
        from .project_documentation_dlt import DLT_TYPES, dlt_profile
        from .project_documentation_neo_usage import neo_action_selector_usage
        profile = None
        if typ in DLT_TYPES:
            try:
                profile = dlt_profile(unit)
            except ValueError as exc:
                return _missing(str(exc))
        return neo_action_selector_usage(unit, application, group, address, value, profile=profile)
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
    key_count = _classic_usage_count(unit)
    if action_documentor != "ClassicKeyInput" or key_count is None:
        return _missing("ActionSelectorUse implementation")
    primary = _application(unit)
    if primary is None:
        return _missing("Application")
    if primary != application:
        return Usage()
    names = ("GroupAddress", "BlockAllocation", "LightLevelStore1", "LightLevelStore2",
             "TimerExpiryCommand", *STAGES)
    counts = (4, key_count, 4, 4, 4, *([key_count] * 4))
    arrays = [_array(unit, name, count, 15 if name in (*STAGES, "TimerExpiryCommand") else 255)
              for name, count in zip(names, counts)]
    missing = [name for name, values in zip(names, arrays) if values is None]
    if missing:
        return _missing(*missing)
    groups, masks, stored1, stored2, expiry, *stages = arrays
    descriptions = []
    for key in range(key_count):
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
