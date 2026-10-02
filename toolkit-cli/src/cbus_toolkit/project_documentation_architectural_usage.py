"""Native architectural group and selector descriptions, for fresh loads.

Object identity is (application, group[, Level.Address]). Neither selector
consumer reads Level.Value. Special scene group collections are unprepared in
the pinned loader and do not acquire ordinary scene groups by inference.
"""
from __future__ import annotations

from .project_documentation_devices import _required_array
from .project_documentation_architectural_loader import (
    SCENE_SLOTS, _bits, _byte, architectural_profile, architectural_scenes,
)
from .project_documentation_usage import Usage


def architectural_group_usage(unit, application, group, kind):
    if kind not in {'input', 'output', 'other'}:
        raise ValueError('Group usage kind must be input, output or other')
    try:
        count = architectural_profile(unit)
        if kind == 'other':
            if application != 203:
                return Usage()
            fields = (('ChannelEnableGroup', 'Channel C-Bus disable Group'),
                      ('DMXEnableGroup', 'Enable DMX by Set allocation'),
                      ('EnableErrorGroup', 'Error Report Enable Group'))
            return Usage('<br/>'.join(label for field, label in fields if _byte(unit, field) == group))
        primary = _byte(unit, 'Application')
        if primary != application:
            return Usage()
        groups = _required_array(unit, 'GroupAddress', 16)
        if kind == 'output':
            labels = [f'Channel {index + 1}' for index, address in enumerate(groups[:count]) if address == group]
            for index, address in enumerate(groups[12:16]):
                if address == group:
                    used = _required_array(unit, f'LogicGA{13 + index}Associations', count)
                    labels.append('Logic Group' if any(used) else 'Logic Group (Unused)')
            return Usage('<br/>'.join(labels))
        labels = []
        if not _bits(unit, 'DMXModeEnabled', 1)[0] and group in groups[:count]:
            take = _bits(unit, 'DMXDisableOperation', count)
            enable = _byte(unit, 'DMXEnableGroup')
            if enable != 255:
                levels = [_byte(unit, f'DMXEnableMask{mask}Level') for mask in range(1, 5)]
                masks = [_bits(unit, f'DMXChannelMask{mask}', count) for mask in range(1, 5)]
                for index, address in enumerate(groups[:count]):
                    if address == group and not take[index] and any(level != 255 and mask[index] for level, mask in zip(levels, masks)):
                        labels.append('DMX Disable Update C-Bus Level')
        for number, scene in enumerate(architectural_scenes(unit, count=count, output_groups=groups[:count]), 1):
            if any(channel.group == group for channel in scene.groups):
                labels.append(f'Scene {number}')
        # LoadSpecialScenes fills only SceneChannels. PrepareScenesForUnit runs
        # before it and iterates the ordinary collection, never special scenes.
        return Usage('<br/>'.join(labels))
    except ValueError as error:
        return Usage(status='unrecovered', missing=(str(error),))


def architectural_action_selector_usage(unit, application, group, address, value):
    try:
        architectural_profile(unit)
        if application != 202:
            return Usage()
        labels = []
        trigger = _byte(unit, 'TriggerErrorGroup')
        if trigger != 255 and trigger == group:
            for field, label in (('TriggerErrorAcSel', 'Trigger Error Report'),
                                 ('TriggerErrorClearAcSel', 'Trigger Error Report Clear')):
                if _byte(unit, field) == address:
                    labels.append(label)
        # Unit.HalogenCleanActionSelector and SpecialSceneHalogenClean's
        # ActionSelector are separate references. The fresh loader assigns
        # only the former, whereas ActionSelectorUse reads the latter (nil).
        number = 0
        for slot, used in enumerate(_bits(unit, 'SceneUsed', SCENE_SLOTS), 1):
            if not used:
                continue
            number += 1
            raw = _required_array(unit, f'Scene{slot:03d}Data', 2)
            if raw[0] != 255 and (raw[0], raw[1]) == (group, address):
                labels.append(f'Triggers Scene {number}')
        return Usage(''.join('<li />' + label for label in labels))
    except ValueError as error:
        return Usage(status='unrecovered', missing=(str(error),))
