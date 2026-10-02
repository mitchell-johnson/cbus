"""Fresh saved-PP projection for wireless reports; no project mutations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .project_documentation_devices import _required_array
from .project_documentation_outputs import _registration
from .project_documentation_wireless_facts import (
    MACRO_TEMPLATES, MICRO_GROUPS, REMOTE_TYPES, WIRELESS_CLASSES, WIRELESS_TYPES,
)
from .serials import parse_native_serial
from .wireless_gateway import WTXU_KEY_MAP, serial_from_bytes

if TYPE_CHECKING:
    from .project_documentation import Network, Unit


def wireless_profile(unit: Unit) -> tuple[int, bool, bool, int]:
    row = _registration(unit)
    if unit.unit_type in WIRELESS_TYPES and row is not None and row[4] in (
            'TCBusWirelessInputUnitCGateAgent', 'TCBusWirelessInputUnit8RemotesCGateAgent',
            'TCBusWirelessDecoratorInputUnitCGateAgent') and row[3] in WIRELESS_CLASSES:
        return WIRELESS_CLASSES[row[3]]
    raise ValueError('wireless input class/agent firmware profile')


def remote_profile(unit: Unit) -> None:
    row = _registration(unit)
    if unit.unit_type not in REMOTE_TYPES or row is None or row[3:5] not in (
            ('TWTXU', 'TCBusRemoteControlCGateAgent'), ('TWTXUP', 'TCBusRemoteControlCGateAgent')):
        raise ValueError('remote-control class/agent firmware profile')


def gateway_profile(unit: Unit) -> bool:
    row = _registration(unit)
    if unit.unit_type in ('WGATE5N', 'WGATE5F') and row is not None:
        if row[4] == 'TCBusWirelessGatewayCGateAgent' and row[3] in (
                'TCBusWGUnitNoSynchroniseToWired', 'TCBusWGUnitNoRepeatSALTransmission',
                'TCBusWirelessGatewayUnit'):
            return False
        if row[3:5] == ('TCBusWirelessGatewayAdvancedUnit', 'TCBusWirelessGatewayAdvancedCGateAgent'):
            return True
    raise ValueError('wireless gateway class/agent firmware profile')


def command_type(raw: int) -> int:
    """ByteToCommandType plus LoadEvent's missing-command fallback to Idle."""
    if raw <= 32:
        return raw if raw <= 31 else 0
    if raw == 128:
        return 23
    if 192 <= raw <= 198:
        return raw - 168
    return 31 if raw >= 224 else 0


def decorator_load(index: int, visible: int) -> int:
    if index >= visible * 4:
        return index
    return index * 2 if index < visible * 2 else (index - visible * 2) * 2 + 1


def decorator_save(index: int, visible: int) -> int:
    if index >= visible * 4:
        return index
    return index // 2 + (visible * 2 if index % 2 else 0)


@dataclass(frozen=True)
class WirelessScene:
    application: int
    commands: tuple[tuple[int, int], ...]
    trigger_group: int
    trigger_address: int

    @property
    def has_trigger(self) -> bool:
        return self.trigger_group != 255 and self.trigger_address != 255


def wireless_scenes(unit: Unit) -> tuple[WirelessScene, ...]:
    apps = _required_array(unit, 'Application', 2)
    offsets = _required_array(unit, 'SceneVectorOffset', 8)
    valid = [value for value in offsets if value != 255 and (value & 127) < 100]
    if not valid:
        return ()
    vector = _required_array(unit, 'SceneVector', 100)
    groups = _required_array(unit, 'SceneTriggerGroup', len(valid))
    actions = _required_array(unit, 'SceneTriggerLevel', len(valid))
    scenes = []
    for ordinal, offset in enumerate(valid):
        commands = []
        cursor = offset & 127
        while cursor < 100 and vector[cursor] != 255:
            if cursor + 1 >= 100:
                # The original asks its native attribute for an out-of-range
                # default here; a saved snapshot does not establish that state.
                raise ValueError('SceneVector pair at byte 99 lacks its level')
            commands.append((vector[cursor], vector[cursor + 1]))
            cursor += 2
        scenes.append(WirelessScene(apps[bool(offset & 128)], tuple(commands),
                                    groups[ordinal], actions[ordinal]))
    return tuple(scenes)


@dataclass(frozen=True)
class WirelessKey:
    kind: int
    blocks: tuple[int, ...]
    scene: int | None
    scene_key: bool


@dataclass(frozen=True)
class WirelessData:
    applications: tuple[int, int]
    groups: tuple[tuple[int, int], ...]
    memory1: tuple[int, ...]
    memory2: tuple[int, ...]
    expiry: tuple[int, ...]
    timers: tuple[int, ...]
    keys: tuple[WirelessKey, ...]
    scenes: tuple[WirelessScene, ...]


def wireless_key_data(unit: Unit) -> WirelessData:
    visible, decorator, _, _ = wireless_profile(unit)
    apps = tuple(_required_array(unit, 'Application', 2))
    group = _required_array(unit, 'BlockGroup', 16)
    secondary = _required_array(unit, 'BlockGroupSecondary', 16, 1)
    groups = tuple((apps[flag], address) for flag, address in zip(secondary, group))
    memory1 = tuple(_required_array(unit, 'BlockMemory1', 16))
    memory2 = tuple(_required_array(unit, 'BlockMemory2', 16))
    expiry = tuple(command_type(value) for value in _required_array(unit, 'BlockExpiryCommand', 16))
    p1 = _required_array(unit, 'BlockExpiryParameter1', 16)
    p2 = _required_array(unit, 'BlockExpiryParameter2', 16)
    # Only Retrigger Timer and Start load DataTimeSeconds. InternalCreate
    # initializes the fresh event's numeric field to zero for other commands.
    timers = tuple(low + (high << 8) if command in (7, 8) else 0
                   for command, low, high in zip(expiry, p1, p2))
    scenes = wireless_scenes(unit)
    raw = []
    for key in range(1, 17):
        commands = tuple(command_type(value) for value in _required_array(unit, f'Key{key}CommandLookup', 6))
        params = _required_array(unit, f'Key{key}Parameter1', 6)
        # Parameter2 does not affect the report's key template or scene binding.
        blocks = tuple(i for i, flag in enumerate(_required_array(unit, f'Key{key}BlockMap', 16, 1)) if flag)
        raw.append((commands, params, blocks))
    if decorator:
        raw = [raw[decorator_load(i, visible)] for i in range(16)]
    keys = []
    for commands, params, blocks in raw:
        scene_key = any(24 <= command <= 30 for command in commands)
        scene = None
        if scene_key and 30 not in commands:
            index = next(params[i] for i, command in enumerate(commands) if 24 <= command <= 30)
            scene = index if index < len(scenes) else None
        kind = next((kind for kind, _, candidates in MACRO_TEMPLATES
                     if any(commands == MICRO_GROUPS[candidate] for candidate in candidates)), None)
        if kind is None:
            kind = 23 if scene_key else 33 if 31 in commands else 34
        if scene is not None and not scenes[scene].commands:
            kind = 31
        if blocks:
            if kind == 41:
                kind = {249: 41, 252: 42, 255: 44}.get(memory1[blocks[0]], kind)
            elif kind == 43:
                kind = {2: 43, 5: 46}.get(memory2[blocks[0]], kind)
        keys.append(WirelessKey(kind, blocks, scene, scene_key))
    return WirelessData(apps, groups, memory1, memory2, expiry, timers, tuple(keys), scenes)


def wireless_channels(unit: Unit) -> tuple[tuple[int, int, int, int, int], ...]:
    wireless_profile(unit)
    apps = _required_array(unit, 'Application', 2)
    count = _required_array(unit, 'InstalledChannels', 1, 16)[0]
    if not count:
        return ()
    groups = _required_array(unit, 'OutputGroup', count)
    secondary = _required_array(unit, 'OutputGroupSecondary', count, 1)
    curves = _required_array(unit, 'OutputMapping', count)
    minimum = _required_array(unit, 'OutputMinimumLevel', count)
    maximum = _required_array(unit, 'OutputMaximumLevel', count)
    return tuple((apps[s], group, curve & 7 if curve & 7 <= 2 else 1, low, high)
                 for s, group, curve, low, high in zip(secondary, groups, curves, minimum, maximum))


def resolve_remote(network: Network, identity: list[int]) -> Unit | None:
    raw = serial_from_bytes(identity)
    if raw == 0xFFFFFFFF:
        return None
    expected = raw >> 12, raw & 4095
    for unit in network.units:
        if unit.unit_type not in REMOTE_TYPES:
            continue
        remote_profile(unit)
        try:
            serial = parse_native_serial(unit.serial)
        except ValueError:
            continue
        if (serial.first, serial.second) == expected:
            return unit
    raise ValueError(f'unresolved remote serial {expected[0]}.{expected[1]} (original loader would create a Unit)')


def input_remote_maps(network: Network, unit: Unit) -> tuple[tuple[Unit | None, tuple[int | None, ...]], ...]:
    visible, decorator, packed, count = wireless_profile(unit)
    result = []
    for remote in range(1, count + 1):
        selected = resolve_remote(network, _required_array(unit, f'Remote{remote}Identity', 4))
        if selected is None:
            result.append((None, (None,) * 10))
            continue
        values = _required_array(unit, f'Remote{remote}KeyMap', 8 if packed else 16)
        mapping = []
        for slot in WTXU_KEY_MAP[:10]:
            value = ((values[slot // 2] >> (4 * (slot % 2))) & 15) if packed else values[slot]
            if decorator:
                value = decorator_save(value, visible)
            # The eight-remotes loader explicitly discards KeyNumber 16;
            # the byte-map loader resolves 255 to a missing key.
            mapping.append(value if value < (15 if packed else 16) else None)
        result.append((selected, tuple(mapping)))
    return tuple(result)


@dataclass(frozen=True)
class GatewayKey:
    function: int
    application: int
    group: int | None
    scene: int | None


def gateway_remote_data(network: Network, unit: Unit) -> tuple[tuple[WirelessScene, ...], tuple]:
    if not gateway_profile(unit):
        raise ValueError('advanced wireless gateway class/agent firmware profile')
    apps = _required_array(unit, 'Application', 2)
    scenes = wireless_scenes(unit)
    remotes = []
    for remote in range(1, 9):
        selected = resolve_remote(network, _required_array(unit, f'RemoteIdentity{remote}', 4))
        masks = _required_array(unit, f'KeySceneMask{remote}', 16, 1)
        secondary = _required_array(unit, f'ApplicationSeconday{remote}', 16, 1)
        groups = _required_array(unit, f'GroupAddress{remote}', 16)
        keys = []
        for index in range(16):
            slot = WTXU_KEY_MAP[index] if selected is not None else index
            value = groups[slot]
            if masks[slot]:
                scene = value >> 4
                keys.append(GatewayKey(1 if value & 15 == 1 else 2, apps[0], None,
                                       scene if scene < len(scenes) else None))
            else:
                # LoadRemoteKeys gates assignment on primary != 255, even
                # when ApplicationSeconday requests the secondary application.
                keys.append(GatewayKey(0, apps[secondary[slot]], value if apps[0] != 255 else None, None))
        remotes.append((selected, tuple(keys)))
    return scenes, tuple(remotes)
