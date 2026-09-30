"""Source-bounded WGATE5F scene replacement with existing project metadata.

Combines the Scene Manager command list and scene-detail controls. This is not
its interactive event sequence, automatic load-time metadata creation, or the
whole gateway dialog save. Remote mapping bytes are preserved, never repaired.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType
import xml.etree.ElementTree as ET

from .macros import _numbers
from .memory import MemoryCodec
from .wireless_connection import (FrozenTopology, MAX_PROJECT_XML_BYTES, _address,
                                  _byte, _canonical, _children, _field)
from .wireless_gateway import LAYOUT as REMOTE_LAYOUT, SPEC_FILENAME, check_profile, verify_native_schema


class WirelessScenesError(ValueError):
    pass


class WirelessScenesApplyError(RuntimeError):
    def __init__(self, cause, attempted):
        self.details = {'attempted_parameters': list(attempted), 'saved': False,
                        'device_verified': False, 'retry_performed': False}
        super().__init__('Wireless scene staging stopped; changes may be partial and were not saved: ' + str(cause))


PLAN_FORMAT = 'cbus-wireless-scenes-plan-v1'
PROJECT_FORMAT = 'cbus-wireless-scenes-project-v1'
OWNED = MappingProxyType({
    'SceneTriggerGroup': (0x130, 8, 8, 0, 0, 'int'),
    'SceneTriggerLevel': (0x138, 8, 8, 0, 0, 'int'),
    'SceneTriggerRate': (0x140, 8, 8, 0, 0, 'int'),
    'SceneVectorOffset': (0x150, 8, 8, 0, 0, 'int'),
    'SceneVector': (0x158, 100, 8, 0, 0, 'int'),
})
LAYOUT = MappingProxyType({**REMOTE_LAYOUT, **OWNED})
FIELDS = tuple(LAYOUT)


@dataclass(frozen=True)
class FrozenSceneProject:
    """Immutable topology plus application/group/action facts from one snapshot."""
    topology: FrozenTopology
    metadata: str

    def __post_init__(self):
        if type(self.topology) is not FrozenTopology:
            raise WirelessScenesError('Expected frozen project topology')
        try:
            rows = json.loads(self.metadata)
        except (ValueError, TypeError) as error:
            raise WirelessScenesError('Invalid scene metadata') from error
        if self.metadata != _canonical(rows) or not isinstance(rows, list):
            raise WirelessScenesError('Scene metadata must be canonical')
        networks = {n['address']: n for n in self.topology.facts['networks']}
        if [r.get('network') for r in rows if isinstance(r, dict)] != sorted(networks):
            raise WirelessScenesError('Scene metadata networks differ from topology')
        for row in rows:
            if set(row) != {'network', 'applications'} or not isinstance(row['applications'], list):
                raise WirelessScenesError('Invalid scene metadata network')
            apps = row['applications']
            if [a.get('address') for a in apps if isinstance(a, dict)] != networks[row['network']]['applications']:
                raise WirelessScenesError('Scene metadata applications differ from topology')
            for app in apps:
                if set(app) != {'address', 'tag', 'groups'} or not isinstance(app['tag'], str) or not isinstance(app['groups'], list):
                    raise WirelessScenesError('Invalid scene application metadata')
                seen = set()
                for group in app['groups']:
                    if not isinstance(group, dict) or set(group) != {'address', 'tag', 'levels'} or not isinstance(group['tag'], str):
                        raise WirelessScenesError('Invalid scene group metadata')
                    address = _byte(group['address'], 'Group address', 255)
                    if address in seen:
                        raise WirelessScenesError('Ambiguous scene group address')
                    seen.add(address)
                    if not isinstance(group['levels'], list):
                        raise WirelessScenesError('Invalid scene action metadata')
                    levels = set()
                    for level in group['levels']:
                        if not isinstance(level, dict) or set(level) != {'address', 'value', 'tag'} or not isinstance(level['tag'], str):
                            raise WirelessScenesError('Invalid scene action metadata')
                        address = _byte(level['address'], 'Action address', 255)
                        _byte(level['value'], 'Action value', 255)
                        if address in levels:
                            raise WirelessScenesError('Ambiguous scene action address')
                        levels.add(address)

    @classmethod
    def from_xml(cls, payload):
        if type(payload) is not bytes or b'\x00' in payload:
            raise WirelessScenesError('Scene project must be UTF-8 XML bytes')
        try:
            payload.decode('utf-8-sig')
        except UnicodeError as error:
            raise WirelessScenesError('Scene project must be UTF-8 XML bytes') from error
        topology = FrozenTopology.from_xml(payload)  # size / DTD / identity bounds
        root = ET.fromstring(payload)
        project = root if root.tag.rsplit('}', 1)[-1] == 'Project' else _children(root, 'Project')[0]
        rows = []
        for net in _children(project, 'Network'):
            apps = []
            for app in _children(net, 'Application'):
                groups = []
                for group in _children(app, 'Group'):
                    levels = []
                    for level in _children(group, 'Level'):
                        if 'Value' in level.attrib and _children(level, 'Value'):
                            raise WirelessScenesError('Ambiguous action Value attribute and child')
                        value = level.attrib.get('Value') if 'Value' in level.attrib else _field(level, 'Value', required=True)
                        if not value.isdecimal() or len(value) > 3:
                            raise WirelessScenesError('Action value must be a decimal byte')
                        levels.append({'address': _address(level, 255), 'value': int(value), 'tag': _field(level, 'TagName')})
                    groups.append({'address': _address(group, 255), 'tag': _field(group, 'TagName'),
                                   'levels': sorted(levels, key=lambda l: l['address'])})
                apps.append({'address': _address(app, 255), 'tag': _field(app, 'TagName'),
                             'groups': sorted(groups, key=lambda g: g['address'])})
            rows.append({'network': _address(net), 'applications': sorted(apps, key=lambda a: a['address'])})
        return cls(topology, _canonical(sorted(rows, key=lambda n: n['network'])))

    @property
    def fingerprint(self):
        return hashlib.sha256((self.topology.document + self.metadata).encode()).hexdigest()

    def as_dict(self):
        return {'format': PROJECT_FORMAT, 'topology': self.topology.as_dict(),
                'metadata': json.loads(self.metadata), 'facts_sha256': self.fingerprint}

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) != {'format', 'topology', 'metadata', 'facts_sha256'} or data['format'] != PROJECT_FORMAT:
            raise WirelessScenesError('Invalid frozen scene project')
        result = cls(FrozenTopology.from_dict(data['topology']), _canonical(data['metadata']))
        if data['facts_sha256'] != result.fingerprint:
            raise WirelessScenesError('Scene metadata fingerprint mismatch')
        return result

    def applications(self, network):
        return {a['address']: a for n in json.loads(self.metadata) if n['network'] == network for a in n['applications']}


def _scenes(value):
    if not isinstance(value, (list, tuple)) or len(value) > 8:
        raise WirelessScenesError('Scenes must be a list of at most eight scene definitions')
    result = []
    for row in value:
        if not isinstance(row, dict) or set(row) != {'application', 'trigger_group', 'trigger_level', 'rate', 'entries'}:
            raise WirelessScenesError('Scene requires application, trigger_group, trigger_level, rate and entries')
        if row['application'] not in ('primary', 'secondary'):
            raise WirelessScenesError('Scene application must be primary or secondary')
        for field, maximum in (('trigger_group', 255), ('trigger_level', 255), ('rate', 15)):
            _byte(row[field], field, maximum)
        if row['trigger_group'] == 255 and row['trigger_level'] != 255:
            raise WirelessScenesError('Unused trigger group requires unused action selector')
        if not isinstance(row['entries'], (list, tuple)):
            raise WirelessScenesError('Scene entries must be a list')
        seen, entries = set(), []
        for entry in row['entries']:
            if not isinstance(entry, dict) or set(entry) != {'group', 'level'}:
                raise WirelessScenesError('Each scene entry requires group and level')
            group, level = _byte(entry['group'], 'Command group'), _byte(entry['level'], 'Command level', 255)
            if group in seen:
                raise WirelessScenesError('A scene cannot add the same group twice')
            seen.add(group)
            entries.append({'group': group, 'level': level})
        result.append({**row, 'entries': entries})
    if sum(2 * len(s['entries']) + 1 for s in result) > 100:
        raise WirelessScenesError('Scene vectors exceed the 100-byte allocation')
    return result


def decode(current):
    """Decode the admitted contiguous slot form; reject lossy original compaction."""
    result, unused = [], False
    for index, offset in enumerate(current['SceneVectorOffset']):
        if offset == 255:
            unused = True
            continue
        if unused or offset & 127 >= 100:
            raise WirelessScenesError('Sparse or invalid scene offsets require original load dependency review')
        if current['SceneTriggerRate'][index] > 15:
            raise WirelessScenesError('Configured scene ramp rate is outside the original enum range')
        cursor, entries = offset & 127, []
        vector = current['SceneVector']
        while cursor < 100 and vector[cursor] != 255:
            if cursor + 1 >= 100:
                raise WirelessScenesError('Scene command crosses the vector boundary')
            entries.append({'group': vector[cursor], 'level': vector[cursor + 1]})
            cursor += 2
        if cursor >= 100:
            raise WirelessScenesError('Scene vector lacks a terminator')
        result.append({'application': 'secondary' if offset & 128 else 'primary',
                       'trigger_group': current['SceneTriggerGroup'][index],
                       'trigger_level': current['SceneTriggerLevel'][index],
                       'rate': current['SceneTriggerRate'][index], 'entries': entries})
    return result


def _planned(current, project, source_network, unit_address, identity, scenes):
    if type(project) is not FrozenSceneProject:
        raise WirelessScenesError('Expected a frozen scene project')
    _, unit = project.topology.selected(source_network, unit_address)
    check_profile(*identity)
    if tuple(identity[:2]) != (unit['unit_type'], unit['firmware']) or (identity[2] or '') != unit['catalog_number']:
        raise WirelessScenesError('Identity differs from the frozen selected gateway')
    if current['MapWirelessRemotes'] != (1,):
        raise WirelessScenesError('Scenes tab is hidden outside Wireless Remotes mode')
    loaded_scenes = decode(current)  # refuse unsupported loaded compaction before changes
    scenes = _scenes(scenes)
    apps = project.applications(source_network)
    if 202 not in apps:
        raise WirelessScenesError('Existing Trigger Control metadata is required; automatic load-time creation is outside this workflow')
    triggers = {g['address']: g for g in apps[202]['groups']}
    for scene in [*loaded_scenes, *scenes]:
        app = current['Application'][scene['application'] == 'secondary']
        if app == 255 or app not in apps:
            raise WirelessScenesError('Scene needs an existing selected primary/secondary application')
        groups = {g['address'] for g in apps[app]['groups']}
        if any(e['group'] not in groups for e in scene['entries']):
            raise WirelessScenesError('Scene command group metadata is missing')
        trigger, action = scene['trigger_group'], scene['trigger_level']
        if trigger not in triggers:
            raise WirelessScenesError('Scene trigger group metadata is missing (including unused group 255)')
        if trigger != 255:
            if action != 255 and not any(l['address'] == action and l['value'] == action for l in triggers[trigger]['levels']):
                raise WirelessScenesError('Scene action metadata is missing or has unsupported value')
    # Original scene objects are retained by ordinal. Preserve the encoded
    # ordinal references and refuse edits which would need remote repair.
    for remote in range(1, 9):
        for key, is_scene in enumerate(current[f'KeySceneMask{remote}']):
            if not is_scene:
                continue
            encoded = current[f'GroupAddress{remote}'][key]
            ordinal, command = encoded >> 4, encoded & 15
            if command not in (1, 6) or ordinal >= len(loaded_scenes):
                raise WirelessScenesError('Existing remote scene reference is invalid in the loaded scene table')
            if ordinal >= len(scenes):
                raise WirelessScenesError('Scene replacement would invalidate an existing remote scene reference')
            scene = scenes[ordinal]
            if scene['trigger_group'] == 255 or scene['trigger_level'] == 255 or (command == 6 and not scene['entries']):
                raise WirelessScenesError('Existing remote scene key needs assigned trigger/action and nonempty Scene Toggle')
    arrays = {name: [0 if name == 'SceneTriggerRate' else 255] * 8 for name in OWNED if name != 'SceneVector'}
    vector, cursor = list(current['SceneVector']), 0
    for index, scene in enumerate(scenes):
        arrays['SceneTriggerGroup'][index] = scene['trigger_group']
        arrays['SceneTriggerLevel'][index] = scene['trigger_level']
        arrays['SceneTriggerRate'][index] = scene['rate']
        arrays['SceneVectorOffset'][index] = cursor | (128 if scene['application'] == 'secondary' else 0)
        prefix = [value for entry in scene['entries'] for value in (entry['group'], entry['level'])] + [255]
        vector[cursor:cursor + len(prefix)] = prefix
        cursor += len(prefix)
    arrays['SceneVector'] = vector  # preserve every old byte after new prefix
    return {name: tuple(values) for name, values in arrays.items()}


@dataclass(frozen=True)
class WirelessScenesPlan:
    expected: dict
    changes: dict
    project: FrozenSceneProject
    source_network: int
    unit_address: int
    identity: tuple
    scene_document: str

    def __post_init__(self):
        try:
            for name in ('expected', 'changes'):
                object.__setattr__(self, name, MappingProxyType({k: tuple(v) for k, v in getattr(self, name).items()}))
            object.__setattr__(self, 'identity', tuple(self.identity))
        except (TypeError, AttributeError) as error:
            raise WirelessScenesError('Invalid scene plan collections') from error

    @property
    def scenes(self):
        return json.loads(self.scene_document)

    def validate(self):
        if len(self.identity) != 3 or set(self.expected) != set(FIELDS) or set(self.changes) - set(OWNED):
            raise WirelessScenesError('Invalid scene plan identity or parameter ownership')
        for name, layout in LAYOUT.items():
            for value in (self.expected[name], self.changes.get(name, self.expected[name])):
                if len(value) != layout[1] or any(type(v) is not int or not 0 <= v <= (1 if layout[5] == 'bit' else 255) for v in value):
                    raise WirelessScenesError('Invalid scene parameter: ' + name)
        scenes = _scenes(self.scenes)
        if _canonical(scenes) != self.scene_document:
            raise WirelessScenesError('Scene definition must be canonical')
        updates = _planned(self.expected, self.project, self.source_network, self.unit_address, self.identity, scenes)
        if dict(self.changes) != {k: v for k, v in updates.items() if v != self.expected[k]}:
            raise WirelessScenesError('Scene plan changes differ from scene definitions and preserved vector tail')

    def as_dict(self):
        return {'format': PLAN_FORMAT, 'unit_type': self.identity[0], 'firmware': self.identity[1],
                'catalog_number': self.identity[2], 'spec_filename': SPEC_FILENAME, 'project': self.project.as_dict(),
                'source_network': self.source_network, 'unit_address': self.unit_address, 'scenes': self.scenes,
                'expected': {k: list(v) for k, v in self.expected.items()},
                'changes': {k: list(v) for k, v in self.changes.items()}, 'saved': False,
                'metadata_created': False, 'remote_mappings_preserved': True,
                'original_toolkit_executed': False, 'whole_dialog_save_executed': False, 'device_verified': False}

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or data.get('format') != PLAN_FORMAT:
            raise WirelessScenesError('Expected ' + PLAN_FORMAT)
        try:
            result = cls(data['expected'], data['changes'], FrozenSceneProject.from_dict(data['project']),
                         data['source_network'], data['unit_address'],
                         (data['unit_type'], data['firmware'], data.get('catalog_number')), _canonical(data['scenes']))
            result.validate()
            return result
        except (KeyError, TypeError, AttributeError) as error:
            raise WirelessScenesError('Incomplete scene plan') from error


class WirelessScenesEditor:
    def __init__(self, spec):
        if spec.filename != SPEC_FILENAME:
            raise WirelessScenesError('Use ' + SPEC_FILENAME + ' for the admitted gateway profile')
        self.spec, self.codec = spec, MemoryCodec(spec)
        for name, expected in LAYOUT.items():
            try:
                row = self.codec.layout(name)
                actual = (row.address, row.array_size, row.bit_size, row.bit_address, row.array_skip, row.parameter.type)
            except Exception as error:
                raise WirelessScenesError('Unsupported scene layout: ' + name) from error
            if actual != expected:
                raise WirelessScenesError('Unsupported scene layout: ' + name)

    def snapshot(self, current):
        result = {}
        for name, layout in LAYOUT.items():
            try:
                values = _numbers(current[name])
            except (KeyError, TypeError, ValueError) as error:
                raise WirelessScenesError('Missing or invalid scene parameter: ' + name) from error
            if len(values) != layout[1] or any(type(v) is not int or not 0 <= v <= (1 if layout[5] == 'bit' else 255) for v in values):
                raise WirelessScenesError('Invalid scene parameter: ' + name)
            result[name] = values
        return result

    def plan(self, current, *, project, source_network, unit_address, scenes, identity=None):
        _, unit = project.topology.selected(source_network, unit_address)
        identity = identity or (unit['unit_type'], unit['firmware'], unit['catalog_number'] or None)
        original = self.snapshot(current)
        desired = _scenes(scenes)
        updates = _planned(original, project, source_network, unit_address, identity, desired)
        changes = {k: v for k, v in updates.items() if v != original[k]}
        self.codec.encode_many(changes)
        return WirelessScenesPlan(original, changes, project, source_network, unit_address, identity, _canonical(desired))

    def show(self, current):
        values = self.snapshot(current)
        return {'format': 'cbus-wireless-scenes-v1', 'scenes': decode(values),
                'scene_controls_visible': values['MapWirelessRemotes'] == (1,),
                'vector': list(values['SceneVector']), 'metadata_created': False, 'device_verified': False}

    def apply(self, session, plan, *, project, exclusive_project=False):
        if type(plan) is not WirelessScenesPlan:
            raise WirelessScenesError('Expected a scene plan')
        plan.validate()
        if exclusive_project is not True:
            raise WirelessScenesError('Scene apply requires exclusive project ownership')
        if type(project) is not FrozenSceneProject or project.fingerprint != plan.project.fingerprint:
            raise WirelessScenesError('Project scene metadata changed since planning')
        network = f'//{project.topology.facts["project"]}/{plan.source_network}'
        if getattr(session, 'source', None) != f'/db{network}/p/{plan.unit_address}' or getattr(session, 'lock_address', None) != network:
            raise WirelessScenesError('Scene source and lock must exactly match the planned database gateway')
        if (session.unit_type, session.firmware, getattr(session, 'catalog_number', None)) != plan.identity:
            raise WirelessScenesError('Native session identity differs from the scene plan')
        self.codec.encode_many(plan.changes)
        verify_native_schema(session, self.spec, FIELDS, WirelessScenesError)
        before = session.values()
        if self.snapshot(before) != dict(plan.expected):
            raise WirelessScenesError('PP parameters changed since the scene plan was created')
        attempted = []
        try:
            for name in OWNED:
                if name in plan.changes:
                    attempted.append(name)
                    session.set(name, ' '.join(map(str, plan.changes[name])))
            after = session.values()
            if self.snapshot(after) != {**plan.expected, **plan.changes}:
                raise WirelessScenesError('Scene PP readback differs from the plan')
            if {k: v for k, v in before.items() if k not in OWNED} != {k: v for k, v in after.items() if k not in OWNED}:
                raise WirelessScenesError('Unrelated gateway parameters changed during scene staging')
        except (RuntimeError, OSError, ValueError) as error:
            raise WirelessScenesApplyError(error, attempted) from error
        return {**plan.as_dict(), 'verified': True, 'unrelated_parameters_preserved': True}


def native_project(session, plan, *, exclusive_project=False):
    from .addressing import NetworkAddressing
    from .native import NativeDatabase
    from .programming import xml_text
    plan.validate()
    if exclusive_project is not True:
        raise WirelessScenesError('Scene apply requires exclusive project ownership')
    name = plan.project.topology.facts['project']
    network = f'//{name}/{plan.source_network}'
    if session.source != f'/db{network}/p/{plan.unit_address}' or session.lock_address != network:
        raise WirelessScenesError('Scene source and lock must exactly match the planned database gateway')
    client = session.programmer.client
    reply = NativeDatabase(client).get('//' + name, xml=True)
    if reply.code != 344:
        raise WirelessScenesError('Native project XML response did not complete')
    project = FrozenSceneProject.from_xml(xml_text(reply).encode())
    if project.fingerprint != plan.project.fingerprint:
        raise WirelessScenesError('Project scene metadata changed since planning')
    for row in project.topology.facts['networks']:
        runtime = dict(NetworkAddressing(client)._runtime(f'//{name}/{row["address"]}'))
        if any(runtime.get(k) != v for k, v in (('InterfaceState', 'closed'), ('TargetInterfaceState', 'closed'), ('SyncState', 'idle'))):
            raise WirelessScenesError('Every project network must be closed with synchronization idle')
    return project
