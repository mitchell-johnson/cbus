"""Ordered group and selector references for wireless report model objects."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .project_documentation_devices import _required_array
from .project_documentation_usage import Usage
from .project_documentation_wireless import receiver_bindings, remote_key_display
from .project_documentation_wireless_loader import (
    gateway_profile, gateway_remote_data, remote_profile, wireless_channels,
    wireless_key_data, wireless_profile,
)

if TYPE_CHECKING:
    from .project_documentation import Network, Unit


def wireless_group_usage(unit: Unit, application: int, group: int, kind: str) -> Usage:
    try:
        wireless_profile(unit)
        if kind == 'output':
            values = [f'Channel {index}' for index, (app, address, _, _, _) in
                      enumerate(wireless_channels(unit), start=1) if (app, address) == (application, group)]
        elif kind == 'input':
            data = wireless_key_data(unit)
            values = []
            for block, identity in enumerate(data.groups):
                if identity != (application, group):
                    continue
                keys = [f'Key {index}' for index, key in enumerate(data.keys, start=1)
                        if key.kind != 22 and block in key.blocks]
                values.extend(keys or ['Block (Unused)'])
            referenced = {key.scene for key in data.keys if key.scene is not None}
            for index, scene in enumerate(data.scenes):
                for address, _ in scene.commands:
                    if (scene.application, address) == (application, group):
                        values.append(f'Scene {index + 1}' + ('' if index in referenced else ' (Unused)'))
        elif kind == 'other':
            primary = _required_array(unit, 'Application', 2)[0]
            pairs = [(203, 'KeyMaskNetworkVariable', 'Key Mask Control Group'),
                     (primary, 'IndicatorBrightnessActivityGroup', 'Indicator Activity Group'),
                     (primary, 'IndicatorBrightnessBackgroundGroup', 'Indicator Background Group'),
                     (primary, 'IndicatorBrightnessNightlightGroup', 'Indicator Nightlight Group')]
            values = [label for app, name, label in pairs
                      if app == application and _required_array(unit, name, 1)[0] == group]
        else:
            raise ValueError('unknown wireless group usage kind')
    except ValueError as error:
        return Usage(status='unrecovered', missing=(str(error),))
    return Usage('<br/>'.join(values))


def wireless_action_usage(unit: Unit, application: int, group: int, address: int) -> Usage:
    try:
        wireless_profile(unit)
        if application != 202:
            return Usage()
        data = wireless_key_data(unit)
        descriptions = []
        for key in data.keys:
            if key.scene is not None:
                scene = data.scenes[key.scene]
                if scene.has_trigger and (scene.trigger_group, scene.trigger_address) == (group, address):
                    descriptions.append(f'Triggers Scene {key.scene + 1}')
        return Usage('<br />'.join(descriptions))
    except ValueError as error:
        return Usage(status='unrecovered', missing=(str(error),))


def gateway_group_usage(unit: Unit, application: int, group: int, kind: str) -> Usage:
    """Both gateway classes inherit the three empty TCBUSUnit methods."""
    try:
        gateway_profile(unit)
        if kind not in ('input', 'output', 'other'):
            raise ValueError('unknown gateway group usage kind')
        return Usage()
    except ValueError as error:
        return Usage(status='unrecovered', missing=(str(error),))


def gateway_action_usage(network: Network, unit: Unit, application: int, group: int, address: int) -> Usage:
    try:
        advanced = gateway_profile(unit)
        if not advanced or application != 202:
            return Usage()
        scenes, remotes = gateway_remote_data(network, unit)
        values = []
        for remote, keys in remotes:
            if remote is None:
                continue
            for key in keys:
                if key.function and key.scene is not None:
                    scene = scenes[key.scene]
                    if scene.has_trigger and (scene.trigger_group, scene.trigger_address) == (group, address):
                        values.append(f'Triggers Scene {key.scene + 1}')
        return Usage('<br />'.join(values))
    except ValueError as error:
        return Usage(status='unrecovered', missing=(str(error),))


def remote_group_usage(network: Network, unit: Unit, application: int, group: int, kind: str) -> Usage:
    try:
        remote_profile(unit)
        if kind in ('output', 'other'):
            return Usage()
        if kind != 'input':
            raise ValueError('unknown remote group usage kind')
        values = []
        for family, receiver, page, mapping, data in receiver_bindings(network, unit):
            if family == 'input':
                for index, assigned in enumerate(mapping):
                    if assigned is None:
                        continue
                    key = data.keys[assigned]
                    for block in key.blocks:
                        if key.kind != 22 and data.groups[block] == (application, group):
                            values.append(f'Key {index + 1} ({receiver.name} - {receiver.unit_type} - Key {assigned + 1})')
            else:
                scenes, _ = gateway_remote_data(network, receiver)
                # This method loops all 16 gateway keys, including display-
                # hidden keys, and uses the remote display string in its label.
                for index, key in enumerate(mapping):
                    _, title = remote_key_display(unit, index)
                    prefix = f'Key {title} ({receiver.name} - {receiver.unit_type} - Remote {page + 1}'
                    if key.function == 0:
                        if key.group is None:
                            raise ValueError('gateway key Group is undefined because primary Application is 255')
                        if (key.application, key.group) == (application, group):
                            values.append(prefix + ')')
                    else:
                        if key.scene is None:
                            raise ValueError('gateway scene key references a missing compacted scene')
                        scene = scenes[key.scene]
                        for command, (address, _) in enumerate(scene.commands, start=1):
                            if (scene.application, address) == (application, group):
                                # Source 0xefe258 formats command ordinal,
                                # not the scene object's scene number.
                                values.append(prefix + f' - Scene {command})')
        return Usage('<br/>'.join(values))
    except ValueError as error:
        return Usage(status='unrecovered', missing=(str(error),))


def remote_action_usage(unit: Unit, application: int, group: int, address: int) -> Usage:
    try:
        remote_profile(unit)
        return Usage()  # TRemoteControlDocumentor's base-only wrapper.
    except ValueError as error:
        return Usage(status='unrecovered', missing=(str(error),))
