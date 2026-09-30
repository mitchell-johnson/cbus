"""SCNCTL5 documentation from a complete saved PP snapshot.

This projects a fresh original scene model. Original loader failure/default state,
automatic creation of missing groups/levels and generated pages are not observed.
"""
from __future__ import annotations

from dataclasses import dataclass

from .project_documentation_devices import KEY_RAMP_DESCRIPTIONS, _required_array
from .project_documentation_outputs import _registration

SCENE_COUNT = 5
PRIMARY_COUNT = 3
SECONDARY_COUNT = 6
MASTER_SELECTOR_FORMAT_BASIS = "standard tag-name profile; DisplayAddressValue=false (original fresh default)"


def scene_controller_supported(unit) -> bool:
    row = _registration(unit)
    return unit.unit_type.upper() == "SCNCTL5" and row is not None and row[3:5] == (
        "TSCNCTL5", "TCustomSceneControllerCGateAgent")


def _require_profile(unit):
    if not scene_controller_supported(unit):
        raise ValueError("unrecovered scene controller class or firmware")


def _ramp(value: int) -> int:
    return value if value <= 15 else 1 if value == 255 else 15


def _dragan(value: int, custom: int) -> int:
    if value == 255:
        value = 1
    if not 0 <= value <= 5:
        raise ValueError("invalid Dragan ramp rate (requires 0..5 or 255)")
    return (0, 1, 3, 7, 13, custom)[value]


def _groups(unit) -> tuple[int, tuple[tuple[int, ...], ...]]:
    application = _required_array(unit, "Application", 1)[0]
    primary = _required_array(unit, "PrimaryGroupAddress", PRIMARY_COUNT)
    secondary = [_required_array(unit, f"Scene{scene + 1}SecondaryGroupTable", SECONDARY_COUNT * 3)
                 for scene in range(SCENE_COUNT)]
    return application, tuple(tuple(primary + table[1::3]) for table in secondary)


@dataclass(frozen=True)
class SceneCommand:
    group: int
    level: int
    ramp: int
    master_off: bool


@dataclass(frozen=True)
class SceneControllerData:
    application: int
    control_group: int
    master_selector: int
    master_ramp: int
    selectors: tuple[int, ...]
    scenes: tuple[tuple[SceneCommand, ...], ...]


def scene_controller_data(unit) -> SceneControllerData:
    _require_profile(unit)
    application, groups = _groups(unit)
    control = _required_array(unit, "ControlAppGroupAddress", 1)[0]
    master_selector = _required_array(unit, "MasterOffTriggerLevel", 1)[0]
    master_rate = _required_array(unit, "MasterOffRampRate", 1)[0]
    master_custom = _ramp(_required_array(unit, "MasterOffCustomRampRate", 1)[0])
    master_ramp = _dragan(master_rate, master_custom)
    selectors = _required_array(unit, "SceneTriggerLevel", SCENE_COUNT)
    levels = _required_array(unit, "PrimaryGroupAddressLevel", SCENE_COUNT * PRIMARY_COUNT)
    rates = _required_array(unit, "SceneRampRate", SCENE_COUNT)
    custom = _ramp(_required_array(unit, "SceneCustomRampRate", 1)[0])
    allowed = _required_array(unit, "SecondaryMasterOffEnabled", SCENE_COUNT * SECONDARY_COUNT, 1)
    scenes = []
    for scene in range(SCENE_COUNT):
        # The original stores DraganRampRate independently, then SetRampRate(custom).
        # DocumentHTML calls GetRampRate, which returns that generic attribute.
        # Invalid Dragan values take a swallowed exception path, outside admission.
        _dragan(rates[scene], custom)
        commands = [SceneCommand(groups[scene][command], levels[scene * PRIMARY_COUNT + command], custom, True)
                    for command in range(PRIMARY_COUNT)]
        table = _required_array(unit, f"Scene{scene + 1}SecondaryGroupTable", SECONDARY_COUNT * 3)
        commands.extend(SceneCommand(table[3 * command + 1], table[3 * command + 2],
                                     (table[3 * command] >> 3) & 15,
                                     bool(allowed[scene * SECONDARY_COUNT + command]))
                        for command in range(SECONDARY_COUNT))
        scenes.append(tuple(commands))
    return SceneControllerData(application, control, master_selector, master_ramp,
                               tuple(selectors), tuple(scenes))


def _group(network, application, address):
    app = network.application(application)
    group = app.group(address) if app is not None else None
    if group is None:
        raise ValueError(f"unresolved Application {application} Group {address}")
    return group


def _level(network, group, address):
    record = _group(network, 202, group)
    level = next((level for level in record.levels if level.address == address), None)
    if level is None:
        raise ValueError(f"unresolved Application 202 Group {group} Level {address}")
    return level


def scene_controller_lines(network, data: SceneControllerData) -> list[str]:
    """Exact additional TStringList lines; the base unit body is separate."""
    from .project_documentation import html_group
    control = html_group(network, 202, _group(network, 202, data.control_group))
    lines = [f"Control Group: {control}<br />"]
    if data.control_group != 255:
        # Native Level.AsString -> GetExtendedTagName. The original fresh
        # DisplayAddressValue=false default yields the raw tag; registry-enabled
        # decimal/hex address prefixes are outside this offline profile.
        lines.append(f"Master Off Action Selector: {_level(network, data.control_group, data.master_selector).name}<br />")
    lines += [f"Master Off Ramp Rate: {KEY_RAMP_DESCRIPTIONS[data.master_ramp]}<br />",
              "<br />", '<table border="1">',
              "<tr><th>Scene</th>" + ("<th>Trigger</th>" if data.control_group != 255 else "")
              + "<th>Controls</th></tr>"]
    for index, commands in enumerate(data.scenes):
        if all(command.group == 255 for command in commands):
            continue
        lines += ["<tr>", f"<td>{index + 1}</td>"]
        if data.control_group != 255:
            level = _level(network, data.control_group, data.selectors[index])
            lines.append(f'<td><a href="#{network.address}_202_{data.control_group}_{level.address}">{level.name}</a></td>')
        lines += ['<td><table border="1">',
                  "<tr><th>Groups</th><th>Level</th><th>Ramp Rate</th><th>Master Off</th></tr>"]
        for command in commands:
            if command.group == 255:
                continue
            link = html_group(network, data.application, _group(network, data.application, command.group))
            lines.append(f"<tr><td>{link}</td><td>{(command.level + 2) * 100 // 255}%</td>"
                         f"<td>{KEY_RAMP_DESCRIPTIONS[command.ramp]}</td>"
                         f"<td>{'Yes' if command.master_off else 'No'}</td></tr>")
        lines.append("</table></td></tr>")
    lines.append("</table>")
    return lines


def document_scene_controller(out, network, unit) -> str:
    from .project_documentation import document_base
    document_base(out, network, unit)
    try:
        lines = scene_controller_lines(network, scene_controller_data(unit))
    except ValueError as exc:
        out.mark(network, unit, f"Scene controller: {exc}")
        return "partial"
    for line in lines:
        out.add(line)
    return "recovered"


def scene_controller_action_usage(unit, application: int, group: int, address: int, value: int):
    """Native object-identity matching, represented by app/group/Level.Address."""
    from .project_documentation_usage import Usage
    try:
        _require_profile(unit)
        if application != 202:
            return Usage()
        control = _required_array(unit, "ControlAppGroupAddress", 1)[0]
        if control != group:
            return Usage()
        master = _required_array(unit, "MasterOffTriggerLevel", 1)[0]
        selectors = _required_array(unit, "SceneTriggerLevel", SCENE_COUNT)
        _, groups = _groups(unit)
    except ValueError as exc:
        return Usage(status="unrecovered", missing=(str(exc),))
    descriptions = ["Scene Master Off"] if master == address else []
    descriptions += [f"Triggers Scene {index + 1}" for index, scene in enumerate(groups)
                     if selectors[index] == address and any(item != 255 for item in scene)]
    return Usage("<br />".join(descriptions))


def scene_controller_group_usage(unit, application: int, group: int, kind: str):
    from .project_documentation_usage import Usage
    if kind not in {"input", "output", "other"}:
        raise ValueError("Group usage kind must be input, output or other")
    try:
        _require_profile(unit)
        if kind == "output":
            return Usage()
        primary = _required_array(unit, "Application", 1)[0]
        if primary != application:
            return Usage()
        if kind == "other":
            area = _required_array(unit, "AreaGroupAddress", 1)[0]
            return Usage("Area Group" if area == group else "")
        _, scenes = _groups(unit)
    except ValueError as exc:
        return Usage(status="unrecovered", missing=(str(exc),))
    return Usage("<br/>".join(f"Scene {index + 1}" for index, scene in enumerate(scenes)
                              for address in scene if address == group))
