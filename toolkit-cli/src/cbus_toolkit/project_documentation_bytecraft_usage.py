"""DIMPR12 and L1 dependency and action consumers, independently projected."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .project_documentation_devices import _required_array
from .project_documentation_bytecraft_loader import bytecraft_logic, bytecraft_profile
from .project_documentation_usage import Usage

if TYPE_CHECKING:
    from .project_documentation import Unit


def bytecraft_output_group_usage(unit: Unit, application: int, group: int) -> Usage:
    """Project the twelve Bytecraft channel objects in native order.

    Missing PP is refused instead of synthesizing the native loader's defaults.
    The inherited output consumer is empty. L1 appends its one logic group after all matching channels.
    """
    try:
        bytecraft_profile(unit)
        primary = _required_array(unit, "Application", 1)[0]
        groups = _required_array(unit, "GroupAddress", 12)
        logic = bytecraft_logic(unit)
    except ValueError as error:
        return Usage(status="unrecovered", missing=(str(error),))
    # No IsUnused/DMX predicate: address 255 is still a group identity.
    labels = [f"Channel {index + 1}" for index, address in enumerate(groups)
              if (primary, address) == (application, group)]
    if logic is not None and (primary, logic[0]) == (application, group):
        labels.append('Logic Group' if any(value & 1 for value in logic[1]) else 'Logic Group (Unused)')
    return Usage('<br/>'.join(labels))


def bytecraft_action_selector_usage(unit: Unit, application: int, group: int,
                                    address: int, value: int) -> Usage:
    """Append every used scene's recall match, retaining zero-based labels.

    Bytecraft recall objects always belong to Trigger Control application 202.
    Advanced scenes compare the group object; basic scenes compare the exact
    Level object selected by Address. Level.Value is not read by this consumer.
    """
    try:
        bytecraft_profile(unit)
    except ValueError as error:
        return Usage(status='unrecovered', missing=(str(error),))
    if application != 202:
        return Usage()
    try:
        from .project_documentation_bytecraft_loader import decode_bytecraft_scenes
        scenes = decode_bytecraft_scenes(unit)
    except ValueError as error:
        return Usage(status="unrecovered", missing=(str(error),))
    return Usage("".join("<li />" + ("Advanced Trigger" if scene.advanced else "Trigger")
                        + f" Scene {scene.index}" for scene in scenes
                        if not scene.unused and scene.recall_group == group
                        and (scene.advanced or scene.selector_address == address)))


def bytecraft_group_usage(unit: Unit, application: int, group: int, kind: str) -> Usage:
    """Retain native channel/scene order and independent Other field gates."""
    if kind not in {'input', 'output', 'other'}:
        raise ValueError('Group usage kind must be input, output or other')
    if kind == 'output':
        return bytecraft_output_group_usage(unit, application, group)
    try:
        bytecraft_profile(unit)
    except ValueError as error:
        return Usage(status='unrecovered', missing=(str(error),))
    if kind == 'input':
        try:
            primary = _required_array(unit, 'Application', 1)[0]
            if primary != application:
                return Usage()
            groups = _required_array(unit, 'GroupAddress', 12)
            if group not in groups:
                return Usage()
            from .project_documentation_bytecraft_loader import decode_bytecraft_scenes
            scenes = decode_bytecraft_scenes(unit)
        except ValueError as error:
            return Usage(status='unrecovered', missing=(str(error),))
        return Usage('<br/>'.join(f'Scene {scene.index + 1}' + (' (Unused)' if scene.recall_group == 255 else '')
            for channel, channel_group in enumerate(groups) if channel_group == group
            for scene in scenes if not scene.unused and (scene.on[channel] or scene.off[channel])))
    missing, descriptions = [], []
    try:
        primary = _required_array(unit, 'Application', 1)[0]
    except ValueError as error:
        missing.append(str(error))
        primary = None
    fields = []
    if application == primary:
        fields.append(('AreaGroupAddress', 'Area Group'))
    if application == 203:
        fields += [('CBusDisableGroupAddress', 'C-Bus Disable Group'), ('DMXCBusSwitchAddress', 'DMX Switch')]
    for name, label in fields:
        try:
            address = _required_array(unit, name, 1)[0]
        except ValueError as error:
            missing.append(str(error))
        else:
            if address == group:
                descriptions.append(label)
    return Usage('<br/>'.join(descriptions), 'partial' if missing else 'recovered', tuple(missing))
