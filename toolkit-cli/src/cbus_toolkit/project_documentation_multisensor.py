"""Fresh multisensor report and dependency projections from pinned loaders.

The seven factory profiles share the Neo documentor, but their macro subsets,
maintenance block and Other dependencies differ. Active joins and prior GUI
event listeners are outside this saved-snapshot projection.
"""
from __future__ import annotations

from dataclasses import replace

from .project_documentation_devices import _required_array, classic_key_macro
from .project_documentation_neo import NeoProfile, neo_data, neo_body_lines
from .project_documentation_neo_usage import action_usage_from_data
from .project_documentation_outputs import _registration
from .project_documentation_usage import Usage

PROFILE_CLASSES = {
    "TSENPILL": ("TCBusMultisensorCGateAgent", False, False),
    "TST7SENPILL": ("TCBusST7MultisensorCGateAgent", True, False),
    "TSENPILLA": ("TCBusSurfaceMountMultisensorCGateAgent", True, True),
    "TSENPIRIC": ("TCBusSurfaceMountPIRSensorCGateAgent", True, True),
    "TSENLLA": ("TCBusSurfaceMountLightLevelSensorCGateAgent", True, True),
}
TYPES = frozenset(("SENPILL", "SENPILLA", "SENPIRIC", "SENPIRIB", "SENLLA"))
OLD_JOIN_PARAMETERS = ("SingleJoinEnablerControlGroup", "DualJoinEnablerControlGroup",
                       "SingleJoinEnablerGroup", "DualJoinEnablerGroup")
MOVEMENT_MACROS = {(7, 0, 0, 0): (29, "Day Move"),
                   (13, 7, 7, 0): (30, "Night Move"),
                   (13, 7, 0, 7): (33, "Any Move"),
                   (13, 15, 7, 15): (34, "Sunset")}


def multisensor_profile(unit):
    row = _registration(unit)
    profile = PROFILE_CLASSES.get(row[3]) if row is not None else None
    if unit.unit_type.upper() not in TYPES or profile is None or row[4] != profile[0]:
        raise ValueError("unrecovered multisensor class or firmware")
    return row[3], profile[1], profile[2]


def _byte(unit, name, maximum=255):
    return _required_array(unit, name, 1, maximum)[0]


def multisensor_macro(commands, application, stored1, stored2, *, light_level=False):
    """Global first match, SENPILL override, shutter remap, then class subset.

    SENLLA has only a default subset: unlike SENPILL, its Application255 lookup
    does not narrow to Unused. Its default also excludes raw trigger templates.
    """
    commands = tuple(commands)
    movement = MOVEMENT_MACROS.get(commands)
    if movement is not None:
        if (light_level and movement[0] != 34) or (not light_level and application == 255):
            return 26, "<Custom>"
        return movement
    kind, label = classic_key_macro(commands, 0 if light_level and application == 255 else application,
                                    stored1, stored2)
    return (26, "<Custom>") if light_level and kind in (14, 15) else (kind, label)


def multisensor_data(unit):
    cls, pro, _ = multisensor_profile(unit)
    if not pro and any(_byte(unit, name) != 255 for name in OLD_JOIN_PARAMETERS):
        raise ValueError("multisensor active join model state is unrecovered")
    data = neo_data(unit, NeoProfile(8, pro, True),
                    macro_resolver=lambda commands, app, one, two: multisensor_macro(
                        commands, app, one, two, light_level=cls == "TSENLLA"))
    blocks = list(data.blocks)
    # TKeyMacroFunction.AfterChange runs for the movement aliases too. Only
    # the first allocated block receives the zero-to-five-minute default.
    for key in data.keys:
        primary = next((index for index in range(8) if key.mask & (1 << index)), None)
        if key.macro_type in (29, 30, 33, 34) and primary is not None and blocks[primary].timer == 0:
            blocks[primary] = replace(blocks[primary], timer=300)
    return replace(data, blocks=tuple(blocks))


def document_multisensor(out, network, unit):
    from .project_documentation import document_base
    document_base(out, network, unit)
    try:
        lines = neo_body_lines(network, multisensor_data(unit))
    except ValueError as error:
        out.mark(network, unit, f"Multisensor controls/scenes: {error}")
        return "partial"
    for line in lines:
        out.add(line)
    return "recovered"


def _input_usage(unit, application, group):
    data = multisensor_data(unit)
    maintained = _byte(unit, "PECFunctionBlock", 7)
    active = _byte(unit, "PECFunctionActive") > 0
    descriptions = []
    for index, block in enumerate(data.blocks):
        if (block.application, block.group) != (application, group):
            continue
        keys = [f"Key {number + 1}" for number, key in enumerate(data.keys)
                if key.macro_type != 16 and key.mask & (1 << index)]
        descriptions.extend(keys)
        if active and index == maintained:
            descriptions.append("Light Level Maintenance")
        elif not keys:
            descriptions.append("Block (Unused)")
    if application == data.applications[0]:
        for index, scene in enumerate(data.scenes):
            used = any(key.scene_index == index for key in data.keys)
            descriptions.extend(f"Scene {index + 1}" + ("" if used else " (Unused)")
                                for command in scene if command.group == group)
    return Usage("<br/>".join(descriptions))


def _other_usage(unit, application, group):
    _, pro, surface = multisensor_profile(unit)
    data = multisensor_data(unit)
    primary = data.applications[0]
    refs = [(primary, _byte(unit, "AreaGroupAddress"), "Area Group")]
    if pro:
        # Unsupported KeyDisable is explicitly assigned EnableControl/255 by
        # the fresh native agent; the report still compares that object.
        refs.extend(((203, 255, "Key Disable Group"),
                     (primary, _byte(unit, "CorridorMasterGroup"), "Corridor Link Group"),
                     (202, data.trigger_group, "Control App Group")))
    if application == 255 and group == 255 and (pro or unit.unit_type.upper() != "SENLLA"):
        raise ValueError("unused join-group identity is not established by a saved snapshot")
    refs.extend(((primary, _byte(unit, "PECEnablerGroup"), "Light Level Maintenance Enable"),
                 (primary, _byte(unit, "PIREnablerGroup"), "Occupancy Enable"),
                 (primary, _byte(unit, "CorridorMasterGroup" if pro else "CorridorLinkEnablerGroup"), "Corridor Link")))
    broadcast = data.blocks[_byte(unit, "BroadcastBlock", 7)]
    refs.append((broadcast.application, broadcast.group, "Light Level Broadcast Group"))
    if surface:
        target = _byte(unit, "LightLevelTargetGroup")
        # The source writes Margin=255 before loading it whenever Target is
        # used. Reading a missing Margin in that branch would borrow PP state.
        margin = 255 if target != 255 else _byte(unit, "LightLevelMarginGroup")
        bank = _byte(unit, "BankSwitchThresholdGroup")
        low = _byte(unit, "BankSwitchThresholdBehaviour") == 1
        refs.extend(((primary, target, "Light Level Target Group"),
                     (primary, margin, "Light Level Margin Group"),
                     (primary, bank if low else 255, "Bank Switch Low Threshold Group"),
                     (primary, 255 if low else bank, "Bank Switch High Threshold Group")))
    return Usage("<br/>".join(label for app, address, label in refs if (app, address) == (application, group)))


def multisensor_group_usage(unit, application, group, kind):
    if kind not in {"input", "output", "other"}:
        raise ValueError("Group usage kind must be input, output or other")
    try:
        multisensor_profile(unit)
        return Usage() if kind == "output" else (_input_usage(unit, application, group)
                                                 if kind == "input" else _other_usage(unit, application, group))
    except ValueError as error:
        return Usage(status="unrecovered", missing=(str(error),))


def multisensor_action_selector_usage(unit, application, group, address, value):
    try:
        data = multisensor_data(unit)
    except ValueError as error:
        return Usage(status="unrecovered", missing=(str(error),))
    # The selected documentor inherits NeoInput, never NeoProInput. A pro
    # unit model alone must not add secondary-application recall descriptions.
    return action_usage_from_data(replace(data, is_pro=False), application, group, address, value)
