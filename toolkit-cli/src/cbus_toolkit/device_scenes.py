"""Toolkit scene records and Scene key binding for KEYE1 2.5.00.

These are EEPROM scenes, independent of C-Gate filesystem scenes. The helper
edits a PP session and verifies readback; saving and physical transfer remain
explicit. See docs/device-scenes.md for source evidence and bounded coverage.
"""
from dataclasses import dataclass
from types import MappingProxyType
import xml.etree.ElementTree as ET

from .macros import _numbers
from .memory import MemoryCodec
from .programming import xml_text


class DeviceSceneError(ValueError):
    pass


class DeviceSceneApplyError(RuntimeError):
    def __init__(self, cause, attempted):
        self.cause, self.attempted = cause, tuple(attempted)
        self.details = {'attempted_parameters': list(attempted), 'saved': False, 'device_verified': False}
        super().__init__('Device scene edit stopped; PP changes may be partial and were not saved: ' + str(cause))


PROFILE = ('KEYE1', '2.5.00', '5031NMML', 'KEYE.xml')
# CIS_GUI.SecondsInCBusRampRate, original Toolkit EXE VA 0x13B702C.
RAMP_SECONDS = (0, 4, 8, 12, 20, 30, 40, 60, 90, 120, 180, 300, 420, 600, 900, 1020)
# Address, array size, bit width, bit position, byte skip.
LAYOUTS = MappingProxyType({
    'SceneTable': (162, 80, 8, 0, 0), 'SceneTablePointer': (152, 8, 8, 0, 0),
    'SceneKeySelector': (96, 8, 1, 7, 0), 'IndicatorBlockAssignment': (96, 8, 3, 0, 0),
    'JPCommand': (104, 8, 4, 4, 1), 'SRCommand': (104, 8, 4, 0, 1),
    'LPCommand': (105, 8, 4, 4, 1), 'LRCommand': (105, 8, 4, 0, 1),
    'ControlAppGroupAddress': (95, 1, 8, 0, 0),
    'BlockAllocation': (54, 8, 8, 0, 0), 'SecondApplicationBlocks': (69, 1, 8, 0, 0),
    'GroupAddress': (80, 9, 8, 0, 0), 'Application': (33, 2, 8, 0, 0),
    'JoinPrimaryApplication': (90, 1, 8, 0, 0), 'DualJoinPrimaryApplication': (91, 1, 8, 0, 0),
    'JoinSecondaryApplication': (93, 1, 8, 0, 0), 'DualJoinSecondaryApplication': (94, 1, 8, 0, 0),
})
_FIXED = (162, 182, 202, 222, 255, 255, 255, 255)
_JOIN = ('JoinPrimaryApplication', 'DualJoinPrimaryApplication', 'JoinSecondaryApplication', 'DualJoinSecondaryApplication')


def _integer(value, label, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise DeviceSceneError(f'{label} must be an integer in {low}..{high}')
    return value


@dataclass(frozen=True)
class SceneEntry:
    group: int
    level: int

    def __post_init__(self):
        _integer(self.group, 'Scene group', 0, 254)
        _integer(self.level, 'Scene level', 0, 255)

    def as_dict(self):
        return {'group': self.group, 'level': self.level}


def _entries(values):
    result = []
    for value in values:
        if not isinstance(value, SceneEntry):
            raise DeviceSceneError('Scene entries must be SceneEntry(group, level) objects')
        result.append(value)
        if len(result) > 10:
            raise DeviceSceneError('This verified profile supports at most 10 commands per scene')
    if len({entry.group for entry in result}) != len(result):
        raise DeviceSceneError('A scene cannot contain duplicate group addresses')
    return tuple(result)


def _encode(scenes):
    """Literal Delphi fixed/compact serializer for a contiguous active prefix."""
    if len(scenes) != 8 or any(scenes[i] and not scenes[i - 1] for i in range(1, 8)):
        raise DeviceSceneError('Populated scenes must form a contiguous prefix; renumbering is unsupported')
    scenes = tuple(_entries(scene) for scene in scenes)
    if sum(map(len, scenes)) > 40:
        raise DeviceSceneError('The unit has space for 40 scene commands in total')
    count = sum(bool(scene) for scene in scenes)
    table, pointers = [255] * 80, list(_FIXED if count <= 4 else (255,) * 8)
    offset = 0
    for index, scene in enumerate(scenes):
        if not scene:
            break
        if count <= 4:
            offset = index * 20
        else:
            pointers[index] = 162 + offset
        for entry in scene:
            table[offset:offset + 2] = entry.group, entry.level
            offset += 2
    return tuple(table), tuple(pointers)


def _decode(table, pointers):
    """Reject noncanonical data that Toolkit would discard or renumber."""
    if len(table) != 80 or len(pointers) != 8:
        raise DeviceSceneError('Invalid scene table or pointer length')
    active = tuple(value for value in pointers if value != 255)
    if (not active or active[0] != 162 or pointers[:len(active)] != active
            or any(value < 162 or value >= 242 or value % 2 for value in active)
            or any(right <= left for left, right in zip(active, active[1:]))):
        raise DeviceSceneError('Invalid scene pointer order, range or alignment')
    scenes = []
    for index, start in enumerate(active):
        end = active[index + 1] if index + 1 < len(active) else 242
        entries, padding = [], False
        for offset in range(start - 162, end - 162, 2):
            group, level = table[offset:offset + 2]
            if group == 255:
                if level != 255:
                    raise DeviceSceneError('Noncanonical scene padding would lose stored data')
                padding = True
            else:
                if padding:
                    raise DeviceSceneError('Noncanonical scene padding precedes a command')
                entries.append(SceneEntry(group, level))
        scenes.append(_entries(entries))
    scenes.extend([()] * (8 - len(scenes)))
    result = tuple(scenes)
    if _encode(result) != (table, pointers):
        raise DeviceSceneError('Noncanonical scene layout requires explicit migration')
    return result


@dataclass(frozen=True)
class DeviceScenePlan:
    scene: int
    key: int | None
    expected: dict
    changes: dict

    def __post_init__(self):
        for name in ('expected', 'changes'):
            object.__setattr__(self, name, MappingProxyType({key: tuple(value) for key, value in getattr(self, name).items()}))

    def as_dict(self):
        return {'format': 'cbus-device-scene-plan-v1', 'unit_type': PROFILE[0], 'firmware': PROFILE[1],
                'catalog_number': PROFILE[2], 'spec_filename': PROFILE[3], 'scene': self.scene, 'key': self.key,
                'expected': {name: list(value) for name, value in self.expected.items()},
                'changes': {name: list(value) for name, value in self.changes.items()},
                'saved': False, 'device_verified': False}


class DeviceScenes:
    def __init__(self, spec):
        if (spec.unit_type, spec.filename) != (PROFILE[0], PROFILE[3]):
            raise DeviceSceneError('Use KEYE.xml for KEYE1 2.5.00 / 5031NMML')
        self.spec, self.codec = spec, MemoryCodec(spec)
        for name, expected in LAYOUTS.items():
            layout = self.codec.layout(name)
            if layout.parameter.type != 'int' or (layout.address, layout.array_size, layout.bit_size, layout.bit_address, layout.array_skip) != expected:
                raise DeviceSceneError('Unsupported device scene parameter layout: ' + name)

    def snapshot(self, current):
        result = {}
        for name in LAYOUTS:
            if name not in current:
                raise DeviceSceneError('Missing current scene parameter: ' + name)
            values = _numbers(current[name])
            if not self.spec.get(name).validate_value(list(values))['valid']:
                raise DeviceSceneError('Invalid current scene parameter: ' + name)
            result[name] = values
        return result

    def inspect(self, current):
        values = self.snapshot(current)
        scenes = _decode(values['SceneTable'], values['SceneTablePointer'])
        bindings = []
        for index, enabled in enumerate(values['SceneKeySelector']):
            if enabled:
                bindings.append({'key': index + 1, 'physical_key': index == 0,
                                 'function': 'scene' if values['JPCommand'][index] == 14 else 'modify_scene_unsupported',
                                 'scene': values['IndicatorBlockAssignment'][index] + 1,
                                 'ramp_rate': values['SRCommand'][index],
                                 'ramp_seconds': RAMP_SECONDS[values['SRCommand'][index]],
                                 'action_selector': values['LPCommand'][index] * 16 + values['LRCommand'][index]})
        count = sum(bool(scene) for scene in scenes)
        return {'format': 'cbus-device-scenes-v1', 'unit_type': PROFILE[0], 'firmware': PROFILE[1],
                'catalog_number': PROFILE[2], 'application': values['Application'][0],
                'trigger_application': 202, 'trigger_group': values['ControlAppGroupAddress'][0],
                'scenes': [{'scene': index + 1, 'entries': [entry.as_dict() for entry in scene]}
                           for index, scene in enumerate(scenes)],
                'commands_used': sum(map(len, scenes)), 'commands_capacity': 40,
                'scene_learn_compatible': count <= 4, 'layout': 'fixed' if count <= 4 else 'compact',
                'key_bindings': bindings, 'device_verified': False}

    def plan(self, current, *, scene, entries=None, key=None, ramp_rate=None,
             action_selector=None, trigger_group=None, allow_shared_trigger_group=False):
        scene = _integer(scene, 'Scene', 1, 8)
        if not isinstance(allow_shared_trigger_group, bool):
            raise DeviceSceneError('allow_shared_trigger_group must be boolean')
        if key is not None:
            _integer(key, 'Physical KEYE1 key', 1, 1)
        elif ramp_rate is not None or action_selector is not None:
            raise DeviceSceneError('Ramp rate and action selector require key=1')
        original = self.snapshot(current)
        scenes = list(_decode(original['SceneTable'], original['SceneTablePointer']))
        updates = {name: list(value) for name, value in original.items()}
        if entries is not None:
            scenes[scene - 1] = _entries(entries)
            if scenes[scene - 1] and not 48 <= original['Application'][0] <= 95:
                raise DeviceSceneError('Stored scenes require a primary Lighting Type application in 48..95')
            table, pointers = _encode(scenes)
            updates['SceneTable'], updates['SceneTablePointer'] = list(table), list(pointers)
        if key is not None:
            if scenes[scene - 1] and not 48 <= original['Application'][0] <= 95:
                raise DeviceSceneError('Stored scenes require a primary Lighting Type application in 48..95')
            if any(original[name] != (255,) for name in _JOIN):
                raise DeviceSceneError('Join-mode scene key setup is outside this verified workflow')
            if any(mask & 1 for mask in original['BlockAllocation'][1:]):
                raise DeviceSceneError('Linear block 1 is shared; Toolkit block relocation is unsupported')
            existing = original['SceneKeySelector'][0] == 1 and original['JPCommand'][0] == 14
            # For new bindings the caller selects the rate explicitly; never
            # reinterpret an ordinary key micro-function nibble as a rate.
            if ramp_rate is None and not existing:
                raise DeviceSceneError('A new Scene key requires an explicit ramp_rate in 0..15')
            if action_selector is None and not existing:
                raise DeviceSceneError('A new Scene key requires an explicit action_selector in 0..255')
            updates['SceneKeySelector'][0], updates['IndicatorBlockAssignment'][0] = 1, scene - 1
            updates['JPCommand'][0] = 14
            if ramp_rate is not None:
                updates['SRCommand'][0] = _integer(ramp_rate, 'Scene ramp rate code', 0, 15)
            if action_selector is not None:
                selector = _integer(action_selector, 'Action selector', 0, 255)
                updates['LPCommand'][0], updates['LRCommand'][0] = divmod(selector, 16)
            # Direct RefreshBlocksFromTemplateScene branch, with no shared
            # linear block relocation and no guessed changes to timers.
            updates['BlockAllocation'][0] = 1
            updates['SecondApplicationBlocks'][0] &= ~1
            updates['GroupAddress'][0] = 255
        if trigger_group is not None:
            trigger_group = _integer(trigger_group, 'Trigger group', 0, 255)
            shared = any(original['SceneKeySelector'][index] for index in range(1 if key else 0, 8))
            if shared and trigger_group != original['ControlAppGroupAddress'][0] and not allow_shared_trigger_group:
                raise DeviceSceneError('Trigger group is shared by other scene keys; explicitly allow the shared edit')
            updates['ControlAppGroupAddress'][0] = trigger_group
        changes = {name: tuple(value) for name, value in updates.items() if tuple(value) != original[name]}
        self.codec.encode_many(changes)
        return DeviceScenePlan(scene, key, original, changes)

    def _verify_profile(self, session):
        if (session.unit_type, session.firmware, session.catalog_number) != PROFILE[:3]:
            raise DeviceSceneError('Native session must be KEYE1 2.5.00 / 5031NMML')

    def _verify_session(self, session):
        self._verify_profile(session)
        document = xml_text(session.info('*'))
        if '<!DOCTYPE' in document.upper() or '<!ENTITY' in document.upper():
            raise DeviceSceneError('Unsupported native schema declarations')
        try:
            root = ET.fromstring(document)
        except ET.ParseError as error:
            raise DeviceSceneError('Invalid native parameter schema') from error
        fields = {}
        for param in root.iter():
            if param.tag.rsplit('}', 1)[-1] == 'Param':
                row = {child.tag.rsplit('}', 1)[-1]: child.text or '' for child in param}
                if row.get('Name') in fields:
                    raise DeviceSceneError('Duplicate native parameter schema')
                fields[row.get('Name')] = row
        for name in LAYOUTS:
            native, local = fields.get(name, {}), self.spec.get(name).fields
            if native.get('Type', '').lower() != 'int':
                raise DeviceSceneError('Native parameter type mismatch: ' + name)
            for field, default in (('Address', None), ('ArraySize', '1'), ('BitSize', '8'), ('BitAddress', '0'), ('ArraySkip', '0')):
                if _numbers(native.get(field, default)) != _numbers(local.get(field, default)):
                    raise DeviceSceneError(f'Native parameter layout mismatch: {name}/{field}')

    def apply(self, session, plan):
        if not isinstance(plan, DeviceScenePlan) or set(plan.expected) != set(LAYOUTS) or any(name not in LAYOUTS for name in plan.changes):
            raise DeviceSceneError('Plan contains fields outside the scene workflow')
        self.codec.encode_many(plan.changes)
        expected = dict(plan.expected)
        expected.update(plan.changes)
        _decode(expected['SceneTable'], expected['SceneTablePointer'])
        self._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise DeviceSceneError('PP parameters changed since the scene plan was created')
        attempted = []
        try:
            for name, values in plan.changes.items():
                attempted.append(name)
                session.set(name, ' '.join(map(str, values)))
            if self.snapshot(session.values()) != expected:
                raise DeviceSceneError('Native scene readback differs from the plan')
        except (RuntimeError, OSError, ValueError) as error:
            raise DeviceSceneApplyError(error, attempted) from error
        return {**plan.as_dict(), 'verified': True, 'scenes': self.inspect(expected)}

    def configure(self, session, **options):
        self._verify_profile(session)
        return self.apply(session, self.plan(session.values(), **options))
