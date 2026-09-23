"""Compose thermostat unit loading, Enable metadata and levels in one save.

The target is an existing database-only programmable thermostat in a closed
project.  Planning reads one project XML snapshot, applies the retained
AfterLoad and outer/inner scheduling models, and records every application,
NetVar and level required.  Applying creates a backup before mutation, writes
the complete plan, saves the edited project once, reloads it and verifies the
persisted records.  It never opens a network or programs a physical unit.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from uuid import uuid4
from xml.dom import Node

from .addressing import _container
from .native import _project
from .native_thermostat_schedule import (
    NativeThermostatScheduleLevels,
    _byte,
    _children,
    _field,
    _group,
    _json,
    _oid,
    _shape,
)
from .thermostat_schedule_levels import ScheduleLevel
from .thermostat_scheduling import ScheduleGroup, ThermostatScheduling
from .thermostat_unit_load import RAW_FIELDS, ThermostatLoadGroup, ThermostatUnitLoader


PROFILE = 'cbus-native-thermostat-scheduling-composition-v1'


def _unit_path(value):
    if type(value) is not str:
        raise ValueError('Expected an existing database thermostat path')
    match = re.fullmatch(
        r'//([A-Za-z0-9_]{1,8})/(0|[1-9][0-9]{0,2})/p/(0|[1-9][0-9]{0,2})', value)
    if match is None or int(match[2]) > 255 or int(match[3]) > 255:
        raise ValueError('Use //PROJECT/network/p/unit with byte network and unit addresses')
    return value, match[1], '//' + match[1] + '/' + match[2], int(match[3])


def _byte_text(value, name):
    if type(value) is not str or re.fullmatch(r'(?:0[xX]|\$)[0-9A-Fa-f]+|[0-9]+', value) is None:
        raise ValueError('Stored thermostat parameter is not an integer: ' + name)
    if value.startswith('$'):
        number = int(value[1:], 16)
    elif value.lower().startswith('0x'):
        number = int(value[2:], 16)
    else:
        number = int(value, 10)
    if not 0 <= number <= 255:
        raise ValueError('Stored thermostat parameter is not a byte: ' + name)
    return number


def _name(value, label):
    if (type(value) is not str or not value or len(value) > 128
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError(label + ' must be nonempty bounded text without control characters')
    value.encode('utf-8', 'strict')
    return value


def _one(parent, tag, *, address=None):
    rows = _children(parent, tag)
    if address is not None:
        rows = [row for row in rows if _field(row, 'Address') == str(address)]
    if len(rows) != 1:
        raise ValueError('Expected exactly one native ' + tag)
    return rows[0]


@dataclass(frozen=True)
class NativeCompositionGroup:
    identity: str
    address: int
    tag: str
    levels: tuple[ScheduleLevel, ...]
    metadata: str
    level_metadata: tuple[tuple[int, str], ...]

    def load_group(self):
        return ThermostatLoadGroup(self.identity, self.address, self.tag, self.levels)


@dataclass(frozen=True)
class NativeCompositionSnapshot:
    raw: tuple[tuple[str, int], ...]
    unit_identity: tuple[str, str, str | None]
    unit_metadata: str
    application_identity: str | None
    application_tag: str | None
    application_metadata: str | None
    groups: tuple[NativeCompositionGroup, ...]

    def raw_dict(self):
        return dict(self.raw)


def _snapshot(text, network_address, unit_address):
    root = _container(text, 'Installation').documentElement
    project = _one(root, 'Project')
    network = _one(project, 'Network', address=network_address)
    unit = _one(network, 'Unit', address=unit_address)
    unit_type = _field(unit, 'UnitType')
    firmware = _field(unit, 'FirmwareVersion')
    if unit_type != 'PC_TSA':
        raise ValueError('Selected unit is not a PC_TSA programmable thermostat')
    catalog_rows = _children(unit, 'CatalogNumber')
    if len(catalog_rows) > 1:
        raise ValueError('Expected at most one thermostat CatalogNumber')
    catalog = _field(unit, 'CatalogNumber') if catalog_rows else None
    raw = []
    pp = [node for node in _children(unit, 'PP') if node.hasAttribute('Name')]
    for name in RAW_FIELDS:
        rows = [node for node in pp if node.getAttribute('Name') == name]
        if len(rows) != 1 or not rows[0].hasAttribute('Value'):
            raise ValueError('Expected exactly one stored thermostat parameter: ' + name)
        raw.append((name, _byte_text(rows[0].getAttribute('Value'), name)))

    applications = [node for node in _children(network, 'Application')
                    if _field(node, 'Address') == '203']
    if len(applications) > 1:
        raise ValueError('Enable Control application address is duplicated')
    if not applications:
        return NativeCompositionSnapshot(tuple(raw), (unit_type, firmware, catalog),
                                         _json(_shape(unit)), None, None, None, ())
    application = applications[0]
    application_identity = _oid(_field(application, 'OID'))
    application_tag = _field(application, 'TagName')
    attrs = sorted((application.attributes.item(i).name,
                    application.attributes.item(i).value)
                   for i in range(application.attributes.length))
    non_groups = [_shape(node) for node in application.childNodes
                  if not(node.nodeType == Node.ELEMENT_NODE and node.tagName == 'NetVar')]
    application_metadata = _json((attrs, non_groups))
    groups = []
    addresses = set()
    identities = set()
    for node in _children(application, 'NetVar'):
        address = int(_field(node, 'Address'))
        if not 0 <= address <= 255 or address in addresses:
            raise ValueError('Enable Control NetVar addresses must be unique bytes')
        identity, levels, metadata, level_metadata = _group(node.toxml(), address)
        if identity in identities:
            raise ValueError('Enable Control NetVar identities must be unique')
        addresses.add(address); identities.add(identity)
        groups.append(NativeCompositionGroup(identity, address, _field(node, 'TagName'),
                                              levels, metadata,
                                              tuple(sorted(level_metadata.items()))))
    if len(groups) > 256:
        raise ValueError('Enable Control NetVar collection exceeds byte address space')
    return NativeCompositionSnapshot(tuple(raw), (unit_type, firmware, catalog),
                                     _json(_shape(unit)),
                                     application_identity, application_tag,
                                     application_metadata, tuple(groups))


@dataclass(frozen=True)
class NativeThermostatCompositionPlan:
    unit: str
    project: str
    network: str
    networks: tuple[str, ...]
    before_xml: str
    initial: NativeCompositionSnapshot
    load_outcome: object
    scheduling_outcome: object
    expected_groups: tuple[ScheduleGroup, ...]
    created_group_ids: tuple[str, ...]
    policy: str
    application_name: str

    @property
    def mutation_required(self):
        if self.load_outcome.application_created or self.created_group_ids:
            return True
        initial = {group.identity: group for group in self.initial.groups}
        return any({level.address for level in group.levels}
                   != {level.address for level in initial[group.identity].levels}
                   for group in self.expected_groups)

    def as_dict(self):
        initial = {group.identity: group for group in self.initial.groups}
        created_levels = {}
        for group in self.expected_groups:
            old = {level.address for level in initial[group.identity].levels} if group.identity in initial else set()
            missing = [level.address for level in group.levels if level.address not in old]
            if missing:
                created_levels[str(group.address)] = missing
        return {'format': 'cbus-native-thermostat-scheduling-plan-v1',
                'profile': PROFILE, 'unit': self.unit,
                'unit_identity': {'unit_type': self.initial.unit_identity[0],
                                  'firmware': self.initial.unit_identity[1],
                                  'catalog_number': self.initial.unit_identity[2]},
                'project_xml_sha256': hashlib.sha256(self.before_xml.encode('utf-8')).hexdigest(),
                'raw': self.initial.raw_dict(), 'policy': self.policy,
                'load': self.load_outcome.as_dict(),
                'scheduling': self.scheduling_outcome.as_dict(),
                'application_created': self.load_outcome.application_created,
                'created_group_addresses': [next(group.address for group in self.expected_groups
                                                   if group.identity == identity)
                                            for identity in self.created_group_ids],
                'created_level_addresses': created_levels,
                'mutation_required': self.mutation_required,
                'target_project_save_count': 1 if self.mutation_required else 0,
                'backup_source_save_count': 1 if self.mutation_required else 0,
                'closed_networks': list(self.networks),
                'caller_exclusive_project_required': True,
                'physical_device_programmed': False,
                'original_ui_workflow_executed': False,
                'inherited_loader_executed': False,
                'native_collection_order_verified': False}


class NativeThermostatScheduling(NativeThermostatScheduleLevels):
    """Single-use native composition manager for one thermostat unit."""

    def _start(self, operation):
        self.last_result = self.last_error = None
        self.last_evidence_errors = ()
        self._evidence = {'format': 'cbus-native-thermostat-scheduling-result-v1',
            'profile': PROFILE, 'operation': operation, 'state': 'preconditions',
            'complete': False, 'commands': [], 'objects': [], 'levels': [],
            'backup_created': False, 'target_mutation_attempted': False,
            'target_save_attempted': False, 'target_save_confirmed': False,
            'target_project_save_count': 0, 'persistence_verified': False,
            'batch_atomic': False, 'automatic_retries': 0,
            'physical_device_programmed': False, 'original_ui_workflow_executed': False,
            'inherited_loader_executed': False, 'native_collection_order_verified': False,
            'caller_exclusive_project_required': True, 'server_edit_lock_acquired': False}

    def _closed_networks(self, project, text):
        root = _container(text, 'Installation').documentElement
        projects = _children(root, 'Project')
        if len(projects) != 1:
            raise ValueError('Expected exactly one native Project')
        paths = ['//' + project + '/' + str(_byte(_field(node, 'Address')))
                 for node in _children(projects[0], 'Network')]
        if not paths or len(paths) != len(set(paths)):
            raise ValueError('Project must have unique loaded networks')
        for path in paths:
            runtime = dict(self.network_guard._runtime(path))
            if any(runtime.get(name) != value for name, value in (
                    ('InterfaceState', 'closed'), ('TargetInterfaceState', 'closed'),
                    ('SyncState', 'idle'))):
                raise ValueError('Every project network must be closed with synchronization idle')
        return tuple(sorted(paths))

    def plan(self, unit, *, exclusive_project=False, policy='button',
             application_name='Enable Control', group_name='Group', unused_name='<Unused>'):
        self._start('plan-composition')
        try:
            unit, project, network, unit_address = _unit_path(unit)
            if exclusive_project is not True:
                raise ValueError('Caller must exclusively own project editing/reloading')
            if type(policy) is not str or policy not in ('button', 'direct'):
                raise ValueError('Policy must be button or direct')
            application_name = _name(application_name, 'Application name')
            group_name = _name(group_name, 'Standard group name')
            if (type(unused_name) is not str or len(unused_name) > 128
                    or any(ord(char) < 32 or ord(char) == 127 for char in unused_name)):
                raise ValueError('Unused group name must be bounded text without control characters')
            unused_name.encode('utf-8', 'strict')
            if len(self._plans) >= 16:
                raise ValueError('Use a new manager after sixteen issued plans')
            before_xml = self._xml('//' + project)
            networks = self._closed_networks(project, before_xml)
            if network not in networks:
                raise ValueError('Thermostat network is absent from the closed project inventory')
            initial = _snapshot(before_xml, int(network.rsplit('/', 1)[1]), unit_address)
            loader = ThermostatUnitLoader()
            loaded = loader.load(initial.raw_dict(),
                application_present=initial.application_identity is not None,
                groups=tuple(group.load_group() for group in initial.groups),
                group_name=group_name, unused_name=unused_name)
            created_ids = tuple(identity for identity in loaded.saved if identity != 'application')
            for group in loaded.groups:
                if group.identity in created_ids:
                    _name(group.tag, 'Created group name')
            state_data = loaded.scheduling_state()
            group_records = tuple(ScheduleGroup(group['identity'], group['address'],
                                  tuple(ScheduleLevel(**level) for level in group['levels']))
                                  for group in state_data['groups'])
            roles = state_data['roles']
            scheduling = ThermostatScheduling()
            state = scheduling.load(group_records, on=roles['on'], off=roles['off'],
                                    override=roles['override'], enabled=state_data['enabled'])
            levels = scheduling.create_levels(state, policy=policy)
            result = NativeThermostatCompositionPlan(unit, project, network, networks,
                before_xml, initial, loaded, levels, levels.state.groups,
                created_ids, policy, application_name)
            self._plans.append(result); self._plan_fingerprints[id(result)] = repr(result)
            self._evidence.update(state='planned', complete=True, plan=result.as_dict())
            self._finish()
            return result
        except BaseException as error:
            self._fail(error)

    def _issued_composition(self, plan):
        if (type(plan) is not NativeThermostatCompositionPlan
                or not any(plan is value for value in self._plans)
                or self._plan_fingerprints.get(id(plan)) != repr(plan)):
            raise ValueError('Use an unchanged composition plan issued by this manager')

    def _fresh_composition(self, plan, *, exact_xml=False):
        text = self._xml('//' + plan.project)
        if self._closed_networks(plan.project, text) != plan.networks:
            raise ValueError('Project network inventory changed since planning')
        current = _snapshot(text, int(plan.network.rsplit('/', 1)[1]), _unit_path(plan.unit)[3])
        if current != plan.initial or exact_xml and text != plan.before_xml:
            raise ValueError('Thermostat unit or Enable Control metadata changed since planning')

    def _add(self, parent, kind, address, name):
        _name(name, kind + ' name')
        response = self.command('DBADDSAFE ' + parent + ' ' + kind + ' '
                                + str(address) + ' ' + name)
        if response.code != 301 or len(response.lines) != 1 or not response.lines[0].startswith('301 OID='):
            raise RuntimeError('Native ' + kind + ' creation did not return exactly one object ID')
        identity = _oid(response.lines[0][8:])
        check = self.database.get('!' + identity + '/OID')
        if check.code != 342 or list(check.lines) != ['342 !' + identity + '/OID=' + identity]:
            raise RuntimeError('Created ' + kind + ' identity could not be resolved')
        return identity

    def _add_level(self, path, level, known_oids):
        row = {'group_path': path, 'address': level.address,
               'tag': level.tag, 'created': False, 'value_confirmed': False,
               'tag_confirmed': False}
        self._evidence['levels'].append(row)
        identity = self._add(path, 'Level', level.address, 'Level ' + str(level.address))
        if identity in known_oids:
            raise RuntimeError('New level returned an existing object ID')
        known_oids.add(identity); row.update(created=True, oid=identity)
        for field, value, flag in (('Value', level.value, 'value_confirmed'),
                                   ('TagName', level.tag, 'tag_confirmed')):
            row['field_attempted'] = field
            result = self.database.set('!' + identity + '/' + field, value)
            if result.code != 200 or len(result.lines) != 1:
                raise RuntimeError('Native level field update did not complete')
            row[flag] = True
        return identity

    def apply(self, plan, *, backup_project=None):
        self._start('apply-composition')
        try:
            self._issued_composition(plan)
            backup = _project(backup_project) if backup_project is not None else 'B' + uuid4().hex[:7].upper()
            if backup.upper() == plan.project.upper():
                raise ValueError('Backup project must differ from the edited project')
            if id(plan) in self._consumed:
                raise ValueError('This plan already had an apply attempt; review a fresh plan')
            self._consumed.add(id(plan))
            self._evidence.update(unit=plan.unit, backup_project=backup,
                                  plan=plan.as_dict())
            self._fresh_composition(plan, exact_xml=True)
            if not plan.mutation_required:
                self._evidence.update(state='already_present', complete=True)
                return self._finish()
            self._evidence['state'] = 'backup'
            self._evidence['backup_source_save_attempted'] = True
            self._operation('save', plan.project)
            self._evidence['backup_source_save_confirmed'] = True
            self._evidence['backup_copy_attempted'] = True
            self._operation('copy', plan.project, backup)
            self._evidence['backup_created'] = True
            self._fresh_composition(plan)
            self._operation('use', plan.project)
            self._evidence.update(state='creating', target_mutation_attempted=True)
            created_group_oids = {}
            if plan.load_outcome.application_created:
                identity = self._add(plan.network, 'Application', 203, plan.application_name)
                self._evidence['objects'].append({'kind': 'Application', 'address': 203,
                                                  'oid': identity, 'created': True})
            expected = {group.identity: group for group in plan.expected_groups}
            for identity in plan.created_group_ids:
                group = expected[identity]
                oid = self._add(plan.network + '/203', 'NetVar', group.address,
                                next(item.tag for item in plan.load_outcome.groups
                                     if item.identity == identity))
                created_group_oids[identity] = oid
                self._evidence['objects'].append({'kind': 'NetVar', 'address': group.address,
                                                  'oid': oid, 'created': True})
            initial = {group.identity: group for group in plan.initial.groups}
            known_oids = {group.identity for group in plan.initial.groups}
            known_oids.update(level.identity for group in plan.initial.groups for level in group.levels)
            created_level_oids = {}
            for group in plan.expected_groups:
                address = group.address
                path = plan.network + '/203/' + str(address)
                old_addresses = ({level.address for level in initial[group.identity].levels}
                                 if group.identity in initial else set())
                for level in group.levels:
                    if level.address not in old_addresses:
                        created_level_oids[(group.identity, level.address)] = self._add_level(
                            path, level, known_oids)
            self._evidence.update(state='saving', target_save_attempted=True,
                                  target_project_save_count=1)
            self._operation('save', plan.project)
            self._evidence['target_save_confirmed'] = True
            for action in ('close', 'load'):
                self._evidence['project_operation_attempted'] = action
                self._operation(action, plan.project)
            self._verify_composition(plan, created_group_oids, created_level_oids)
            self._evidence.update(state='verified_saved', complete=True,
                                  persistence_verified=True)
            return self._finish()
        except BaseException as error:
            self._fail(error)

    def _verify_composition(self, plan, created_group_oids, created_level_oids):
        text = self._xml('//' + plan.project)
        if self._closed_networks(plan.project, text) != plan.networks:
            raise ValueError('Project networks changed after save/reload')
        actual = _snapshot(text, int(plan.network.rsplit('/', 1)[1]), _unit_path(plan.unit)[3])
        if (actual.raw != plan.initial.raw or actual.unit_identity != plan.initial.unit_identity
                or actual.unit_metadata != plan.initial.unit_metadata):
            raise ValueError('Thermostat unit parameters or identity changed')
        if actual.application_identity is None:
            raise ValueError('Enable Control application is absent after save')
        if plan.initial.application_identity is not None:
            if (actual.application_identity, actual.application_tag, actual.application_metadata) != (
                    plan.initial.application_identity, plan.initial.application_tag,
                    plan.initial.application_metadata):
                raise ValueError('Existing Enable Control application metadata changed')
        elif actual.application_tag != plan.application_name:
            raise ValueError('Created Enable Control application tag differs')
        actual_by_oid = {group.identity: group for group in actual.groups}
        actual_by_address = {group.address: group for group in actual.groups}
        if len(actual_by_address) != len(actual.groups) or len(actual.groups) != len(plan.expected_groups):
            raise ValueError('Saved Enable Control group membership differs')
        initial = {group.identity: group for group in plan.initial.groups}
        for group in plan.expected_groups:
            if group.identity in initial:
                saved = actual_by_oid.get(group.identity)
                baseline = initial[group.identity]
                if saved is None or (saved.address, saved.tag, saved.metadata) != (
                        baseline.address, baseline.tag, baseline.metadata):
                    raise ValueError('Existing Enable Control group metadata changed')
            else:
                saved = actual_by_address.get(group.address)
                if saved is None or saved.identity != created_group_oids[group.identity]:
                    raise ValueError('Created Enable Control group identity differs')
            actual_levels = {level.address: level for level in saved.levels}
            expected_levels = {level.address: level for level in group.levels}
            if set(actual_levels) != set(expected_levels):
                raise ValueError('Saved scheduling level membership differs')
            old = {level.address: level for level in initial[group.identity].levels} if group.identity in initial else {}
            old_metadata = dict(initial[group.identity].level_metadata) if group.identity in initial else {}
            saved_metadata = dict(saved.level_metadata)
            for address, expected_level in expected_levels.items():
                value = actual_levels[address]
                if address in old:
                    baseline = old[address]
                    if value != baseline or saved_metadata[address] != old_metadata[address]:
                        raise ValueError('Existing scheduling level metadata changed')
                elif (value.identity != created_level_oids[(group.identity, address)]
                      or (value.address, value.value, value.tag) !=
                         (address, expected_level.value, expected_level.tag)):
                    raise ValueError('Created scheduling level differs')
        self._evidence['verified_raw'] = actual.raw_dict()
        self._evidence['verified_groups'] = [
            {'oid': group.identity, 'address': group.address, 'tag': group.tag,
             'levels': [level.as_dict() for level in group.levels]}
            for group in actual.groups]
        self._evidence['existing_metadata_preserved'] = True
        self._evidence['unit_record_preserved'] = True
