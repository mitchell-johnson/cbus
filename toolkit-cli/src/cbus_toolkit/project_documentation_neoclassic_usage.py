"""NeoProClassic group dependencies and its Classic-only action report.

KEYC/CIR body and action consumers need no scene table. The inherited Neo input
method still visits scene commands, despite GetScenesEnabled returning false.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .device_scenes import _decode
from .project_documentation_devices import _required_array
from .project_documentation_usage import Usage, _array

if TYPE_CHECKING:
    from .project_documentation import Unit


def _scenes(unit: Unit):
    table = unit.array("SceneTable")
    if table is None or any(not 0 <= value <= 255 for value in table):
        raise ValueError("SceneTable (requires explicit byte values)")
    # GetSceneCommands exits before even reading the pointer parameter here.
    if not table or table[0] == 255:
        return ((),) * 8
    pointers = _array(unit, "SceneTablePointer", 8)
    if len(table) != 80 or pointers is None or len(pointers) != 8:
        raise ValueError("SceneTable/SceneTablePointer require canonical lengths 80/8")
    return _decode(tuple(table), tuple(pointers))


def neoclassic_action_selector_usage(unit: Unit, application: int, group: int,
                                    address: int, value: int) -> Usage:
    from .project_documentation_neoclassic import neoclassic_profile
    try:
        neoclassic_profile(unit)
    except ValueError as error:
        return Usage(status="unrecovered", missing=(str(error),))
    apps = _array(unit, "Application", 1)
    if apps is None:
        return Usage(status="unrecovered", missing=("Application",))
    if application != apps[0]:
        return Usage()
    try:
        from .project_documentation_neoclassic import neoclassic_programming
        programming = neoclassic_programming(unit, include_scene_indexes=False)
        stored1 = _required_array(unit, "LightLevelStore1", 8)
        stored2 = _required_array(unit, "LightLevelStore2", 8)
        expiry = _required_array(unit, "TimerExpiryCommand", 8, 15)
    except ValueError as error:
        return Usage(status="unrecovered", missing=(str(error),))
    descriptions = []
    # Only Classic's primary-app pass runs, across all eight key objects.
    # Its stored-1 Address gate encloses the stored-2 Value branch.
    for key, (mask, microfunctions) in enumerate(zip(programming.masks, programming.commands), 1):
        for block in range(8):
            if (not mask & (1 << block) or (programming.block_applications[block], programming.groups[block]) != (application, group)
                    or stored1[block] != address):
                continue
            if 12 in microfunctions or (7 in microfunctions and expiry[block] == 12):
                descriptions.append(f"Key {key}")
            if stored2[block] == value and (6 in microfunctions or (7 in microfunctions and expiry[block] == 6)):
                descriptions.append(f"Key {key}")
    return Usage("<br/>".join(descriptions))


def neoclassic_group_usage(unit: Unit, application: int, group: int, kind: str) -> Usage:
    from .project_documentation_neoclassic import neoclassic_profile
    if kind not in {"input", "output", "other"}:
        raise ValueError("Group usage kind must be input, output or other")
    try:
        profile = neoclassic_profile(unit)
    except ValueError as error:
        return Usage(status="unrecovered", missing=(str(error),))
    if kind == "output":
        return Usage()
    if kind == "other":
        return _other_usage(unit, application, group)
    try:
        from .project_documentation_neoclassic import neoclassic_programming
        programming = neoclassic_programming(unit, include_scene_indexes=False)
    except ValueError as error:
        return Usage(status="unrecovered", missing=(str(error),))
    missing = []
    scenes = ()
    if application == programming.applications[0]:
        try:
            scenes = _scenes(unit)
            if any(scenes):
                programming = neoclassic_programming(unit)
        except ValueError as error:
            missing.append(str(error))
            scenes = ()
    # Both native join capability methods are constant false, independently of
    # any saved Join* addresses. Only physical keys count in the input scan.
    descriptions = []
    for block in range(8):
        if (programming.block_applications[block], programming.groups[block]) != (application, group):
            continue
        # Ordinary all-idle keys resolve to Unused. Scene24 remains an active
        # template despite its normalized idle commands. Physical keys alone
        # participate in this native scan.
        matches = [f"Key {key + 1}" for key in range(profile.physical_key_count)
                   if programming.masks[key] & (1 << block)
                   and (programming.scene_keys[key] or any(programming.commands[key]))]
        descriptions.extend(matches or ["Block (Unused)"])
    for index, scene in enumerate(scenes):
        if not scene:
            continue
        # Every key's extension participates, including virtual keys. Ordinary
        # keys reference Scene 1; Scene24 keys reference their decoded scene.
        used = index in programming.scene_indexes
        descriptions.extend(f"Scene {index + 1}" + ("" if used else " (Unused)")
                            for command in scene if command.group == group)
    return Usage("<br/>".join(descriptions), "partial" if missing else "recovered", tuple(missing))


def _other_usage(unit: Unit, application: int, group: int) -> Usage:
    descriptions, missing = [], []
    apps = _array(unit, "Application", 1)

    def append(name, label):
        values = _array(unit, name, 1)
        if values is None:
            missing.append(name)
        elif values[0] == group:
            descriptions.append(label)

    if apps is None:
        missing.append("Application")
    elif application == apps[0]:
        append("AreaGroupAddress", "Area Group")
        brightness = unit.parameters.get("IndicatorBrightness")
        if brightness is None:
            missing.append("IndicatorBrightness")
        elif brightness:
            groups = _array(unit, "GroupAddress", 9)
            if groups is None:
                missing.append("GroupAddress")
            elif groups[8] == group:
                descriptions.append("Indicator Brightness Group")
    # Neo's join labels are gated by unsupported capabilities. NeoPro's three
    # following labels are unconditional group identity comparisons.
    if application == 203:
        append("KeyDisableGroup", "Key Disable Group")
    if apps is not None and application == apps[0]:
        append("CorridorMasterGroup", "Corridor Link Group")
    if application == 202:
        append("ControlAppGroupAddress", "Control App Group")
    return Usage("<br/>".join(descriptions), "partial" if missing else "recovered", tuple(missing))
