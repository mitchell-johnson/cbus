"""Enabled thermostat remote references in one bounded settings transaction.

Raw candidate edits precede the recovered agent load, remote validators and
save projection. Missing reference objects are planned in getter order. The
native settings owner performs persistence; this module has no I/O. It does
not replay unrelated inherited HVAC allocation or GUI source-change callbacks.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType
from typing import Mapping
from xml.dom import Node

from .addressing import _container
from .native_thermostat_schedule import _byte, _children, _field, _oid
from .native_thermostat_scheduling import _unit_path
from .thermostat_templates import FAMILIES, ThermostatTemplateError, family_for_unit_type
from .unitspec import UnitSpecError, UnitSpecStore, _integer

FORMAT = 'cbus-thermostat-remote-references-plan-v1'
SETBACK_FIELDS = ('RemoteSetbackControlSource', 'RemoteSetbackOnGroup', 'RemoteSetbackOffGroup')
SCHEDULE_GROUP_FIELDS = ('RemoteScheduleOnGroup', 'RemoteScheduleOffGroup', 'RemoteScheduleOverrideGroup')
PROGRAM_FIELDS = ('EvapProgramEnabled', 'NonEvapProgramEnabled')
REMOTE_EDIT_FIELDS = MappingProxyType({'basic': SETBACK_FIELDS,
    'programmable': SETBACK_FIELDS + SCHEDULE_GROUP_FIELDS})
REMOTE_READ_FIELDS = MappingProxyType({'basic': ('ApplicationNumber',) + SETBACK_FIELDS,
    'programmable': ('ApplicationNumber',) + SETBACK_FIELDS + SCHEDULE_GROUP_FIELDS
                    + ('RemoteScheduleEnable',) + PROGRAM_FIELDS})
MAX_PROJECT_BYTES = 16 * 1024 * 1024
MAX_OBJECTS = 16384


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':'))


def _hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _fail(message):
    raise ThermostatTemplateError(message)


def _canonical(node, *, config=False, unit_oid=None):
    """Full native shape, exempting only known save/reload representation changes."""
    if node.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE):
        return ('text', node.data)
    if node.nodeType == Node.COMMENT_NODE:
        return ('comment', node.data)
    if node.nodeType == Node.PROCESSING_INSTRUCTION_NODE:
        return ('instruction', node.target, node.data)
    if node.nodeType != Node.ELEMENT_NODE:
        _fail('Unsupported project metadata node')
    attrs = sorted((node.attributes.item(i).name, node.attributes.item(i).value)
                   for i in range(node.attributes.length))
    children, parameters = [], []
    selected = (node.tagName == 'Unit' and not node.namespaceURI and unit_oid is not None
                and _field(node, 'OID') == unit_oid)
    for child in node.childNodes:
        element = child.nodeType == Node.ELEMENT_NODE
        if element and config and child.tagName == 'OID' and not child.namespaceURI:
            continue
        if (element and node.tagName == 'Level' and child.tagName == 'TagsDLT'
                and not child.attributes.length and not child.childNodes):
            continue
        if selected and element and child.tagName == 'PP' and not child.namespaceURI and child.hasAttribute('Name'):
            parameters.append((child.getAttribute('Name'), _canonical(child)))
            continue
        children.append(_canonical(child, unit_oid=unit_oid, config=config or (
            element and node.tagName == 'Project' and child.tagName == 'Config' and not child.namespaceURI)))
    if selected:
        return (node.tagName, attrs, children, ('parameters', sorted(parameters)))
    return (node.tagName, attrs, children)


def _all_oids(root):
    """Require real graph identities and fence optional native Interface IDs."""
    required = frozenset(('Network', 'Application', 'Group', 'NetVar', 'Unit', 'Level'))
    result = []

    def visit(node):
        if node.nodeType != Node.ELEMENT_NODE:
            return
        if not node.namespaceURI and (node.tagName in required or node.tagName in ('Project', 'Interface')):
            rows = _children(node, 'OID')
            if len(rows) != 1 and (node.tagName in required or rows):
                _fail('Native ' + node.tagName + ' requires exactly one canonical object identity')
            if rows:
                result.append(_oid(_field(node, 'OID')))
        for child in node.childNodes:
            visit(child)

    visit(root)
    if len(result) != len(set(result)):
        _fail('Native project contains duplicate object identities')
    return tuple(result)


def _all_addresses(root):
    """Reject ambiguous real native collections, including unselected networks."""
    def visit(node):
        if node.nodeType != Node.ELEMENT_NODE:
            return
        if not node.namespaceURI:
            collections = {'Project': (('Network',),), 'Network': (('Unit',), ('Application',)),
                           'Application': (('Group', 'NetVar'),), 'Group': (('Level',),),
                           'NetVar': (('Level',),)}.get(node.tagName, ())
            for kinds in collections:
                rows = [child for child in _children(node)
                        if child.tagName in kinds and not child.namespaceURI]
                addresses = [_byte(_field(row, 'Address')) for row in rows]
                if len(addresses) != len(set(addresses)):
                    _fail('Duplicate native address in ' + '/'.join(kinds) + ' collection')
        for child in node.childNodes:
            visit(child)
    visit(root)


def _document(text):
    if type(text) is not str or len(text.encode('utf-8')) > MAX_PROJECT_BYTES:
        _fail('Supply one bounded complete native project XML snapshot')
    return _container(text, 'Installation')


def _scalar(node, name, *, optional=False):
    if optional and not _children(node, name):
        return None
    return _field(node, name)


def _address_rows(node, kind):
    rows = _children(node, kind)
    result = [(_byte(_field(row, 'Address')), row) for row in rows]
    if len(result) != len({address for address, _ in result}):
        _fail('Duplicate native ' + kind + ' address')
    return result


def _select(rows, address, label):
    matches = [row for value, row in rows if value == address]
    if len(matches) != 1:
        _fail('Expected exactly one selected ' + label)
    return matches[0]


@dataclass(frozen=True)
class RemoteGroup:
    application: int
    address: int
    identity: str
    name: str
    stored_kind: str
    metadata: str

    def as_dict(self):
        return {'application': self.application, 'address': self.address, 'oid': self.identity,
                'name': self.name, 'stored_kind': self.stored_kind, 'metadata_sha256': _hash(self.metadata)}


@dataclass(frozen=True)
class RemoteApplication:
    address: int
    identity: str
    name: str
    groups: tuple[RemoteGroup, ...]
    metadata: str

    def as_dict(self):
        return {'address': self.address, 'oid': self.identity, 'name': self.name,
                'metadata_sha256': _hash(self.metadata), 'groups': [row.as_dict() for row in self.groups]}


@dataclass(frozen=True)
class ProjectGraphSnapshot:
    project: str
    network: int
    unit: int
    unit_path: str
    unit_identity: tuple[tuple[str, str | None], ...]
    applications: tuple[RemoteApplication, ...]
    all_oids: tuple[str, ...]
    shape: str
    xml_sha256: str

    @property
    def fingerprint(self):
        return _hash(self.shape)

    @property
    def object_oids(self):
        return self.all_oids

    def as_dict(self):
        return {'project': self.project, 'network': self.network, 'unit': self.unit,
                'unit_path': self.unit_path, 'identity': dict(self.unit_identity),
                'fingerprint': self.fingerprint, 'xml_sha256': self.xml_sha256,
                'all_oids': list(self.all_oids), 'applications': [a.as_dict() for a in self.applications]}


def _snapshot_project(text, unit_path):
    path, project_name, network_path, address = _unit_path(unit_path)
    network_address = int(network_path.rsplit('/', 1)[1])
    root = _document(text).documentElement
    _all_addresses(root)
    projects = _children(root, 'Project')
    if len(projects) != 1 or _field(projects[0], 'Address').upper() != project_name.upper():
        _fail('Native XML must contain exactly the selected project')
    project = projects[0]
    network = _select(_address_rows(project, 'Network'), network_address, 'network')
    unit = _select(_address_rows(network, 'Unit'), address, 'unit')
    identity = tuple((name, _scalar(unit, name, optional=name == 'CatalogNumber'))
                     for name in ('OID', 'UnitType', 'FirmwareVersion', 'CatalogNumber'))
    _oid(dict(identity)['OID'])
    family_for_unit_type(dict(identity)['UnitType'])
    if not dict(identity)['FirmwareVersion']:
        _fail('Thermostat firmware identity is missing')
    pp_names = [row.getAttribute('Name') for row in _children(unit, 'PP') if row.hasAttribute('Name')]
    if len(pp_names) != len(set(pp_names)):
        _fail('Selected unit contains duplicate PP parameters')
    oids = _all_oids(root)
    if len(oids) > MAX_OBJECTS:
        _fail('Native project graph exceeds the supported object bound')
    applications = []
    for app_address, application in _address_rows(network, 'Application'):
        if app_address == 255:
            _fail('Application address 255 is outside this remote graph profile')
        app_oid = _oid(_field(application, 'OID'))
        groups, addresses = [], set()
        for group in _children(application):
            if group.tagName not in ('Group', 'NetVar') or group.namespaceURI:
                continue
            group_address = _byte(_field(group, 'Address'))
            if group_address in addresses:
                _fail('Duplicate native group address within application ' + str(app_address))
            addresses.add(group_address)
            group_oid = _oid(_field(group, 'OID'))
            _address_rows(group, 'Level')
            groups.append(RemoteGroup(app_address, group_address, group_oid, _field(group, 'TagName'),
                                      group.tagName, _json(_canonical(group))))
        if len(groups) > 256:
            _fail('Remote group collection exceeds the byte address space')
        applications.append(RemoteApplication(app_address, app_oid, _field(application, 'TagName'),
                                              tuple(groups), _json(_canonical(application))))
    return ProjectGraphSnapshot(project_name, network_address, address, path, identity,
        tuple(applications), tuple(oids), _json(_canonical(root, unit_oid=dict(identity)['OID'])), _hash(text))


def snapshot_project(project_xml, unit_path):
    """Validate a complete graph and retain its complete preservation fingerprint."""
    try:
        return _snapshot_project(project_xml, unit_path)
    except ThermostatTemplateError:
        raise
    except (ValueError, KeyError, TypeError) as error:
        raise ThermostatTemplateError('Invalid thermostat project graph: ' + str(error)) from error


def project_fingerprint(project_xml, unit_path):
    return snapshot_project(project_xml, unit_path).fingerprint


@dataclass(frozen=True)
class RemoteCreation:
    kind: str
    application: int
    address: int
    name: str
    reason: str

    @property
    def key(self):
        return self.kind, self.application, self.address

    def as_dict(self):
        return {'kind': self.kind, 'application': self.application, 'address': self.address,
                'name': self.name, 'reason': self.reason}


@dataclass(frozen=True)
class RemoteReferencePlan:
    family: str
    unit_type: str
    before: tuple[tuple[str, str], ...]
    edits: tuple[tuple[str, int], ...]
    project_xml: str
    graph: ProjectGraphSnapshot
    owned_values: tuple[tuple[str, int], ...]
    creations: tuple[RemoteCreation, ...]
    getters_json: str
    roles_json: str
    validation_json: str
    schema_json: str

    @property
    def expected(self):
        return dict(self.owned_values)

    @property
    def changed_parameters(self):
        before = dict(self.before)
        return [{'name': name, 'before': _integer(before[name]), 'after': value}
                for name, value in self.owned_values if _integer(before[name]) != value]

    @property
    def pp_mutation_required(self):
        return bool(self.changed_parameters)

    @property
    def graph_mutation_required(self):
        return bool(self.creations)

    @property
    def apply_would_mutate(self):
        return self.pp_mutation_required or self.graph_mutation_required

    def semantic_source(self):
        return _json({'before': self.before, 'identity': self.graph.unit_identity,
                      'graph': self.graph.fingerprint, 'edits': self.edits, 'schema': self.schema_json})

    def as_dict(self):
        return {'format': FORMAT, 'family': self.family, 'unit_type': self.unit_type,
                'requested': dict(self.edits), 'expected': self.expected,
                'changed_parameters': self.changed_parameters,
                'project_graph': self.graph.as_dict(),
                'planned_creations': [row.as_dict() for row in self.creations],
                'getters': json.loads(self.getters_json), 'resolved_roles': json.loads(self.roles_json),
                'remote_validation': json.loads(self.validation_json),
                'pp_mutation_required': self.pp_mutation_required,
                'graph_mutation_required': self.graph_mutation_required,
                'apply_would_mutate': self.apply_would_mutate,
                'level_creation_policy': 'decline-optional-additions',
                'existing_levels_preserved': True, 'complete_form_lifecycle_reproduced': False,
                'gui_source_change_callbacks_reproduced': False, 'physical_device_programmed': False,
                'saved': False}


def _byte_parameter(spec, name, value):
    parameter = spec.parameters.get(name)
    if (parameter is None or parameter.type != 'int' or parameter.array_size != 1 or parameter.bit_size != 8):
        _fail('Unit specification lacks one-byte remote dependency: ' + name)
    if type(value) not in (int, str):
        _fail('Thermostat setting must be an integer: ' + name)
    checked = parameter.validate_value(value if type(value) is str else str(value))
    if not checked['valid']:
        _fail(name + ': ' + '; '.join(checked['errors']))
    parsed = checked['parsed']
    if type(parsed) is not int or not 0 <= parsed <= 255:
        _fail('Thermostat parameter must fit one unsigned byte: ' + name)
    return parsed


def plan_remote_references(store, unit_type, snapshot, edits, *, project_xml, unit_path):
    """Project all remote fields from one candidate and its authoritative graph.

    Ordinary edits are consumed for the same candidate as the owning settings
    plan, but only remote fields and program-enable normalization are returned.
    """
    try:
        return _plan(store, unit_type, snapshot, edits, project_xml=project_xml, unit_path=unit_path)
    except ThermostatTemplateError:
        raise
    except (ValueError, KeyError, TypeError, UnitSpecError) as error:
        raise ThermostatTemplateError('Invalid thermostat remote reference plan: ' + str(error)) from error


def _plan(store, unit_type, snapshot, edits, *, project_xml, unit_path):
    if not isinstance(store, UnitSpecStore):
        _fail('Remote reference planning requires a decoded UnitSpecStore')
    family = family_for_unit_type(unit_type)
    spec = store.load(FAMILIES[family]['unit_spec'])
    if spec.unit_type != {'basic': 'THERMOSTATB', 'programmable': 'THERMOSTATA'}[family]:
        _fail('Decoded thermostat specification identity differs from the selected family')
    if not isinstance(snapshot, Mapping) or any(type(k) is not str or type(v) is not str for k, v in snapshot.items()):
        _fail('Full thermostat snapshot must map parameter names to raw native value strings')
    if not isinstance(edits, Mapping):
        _fail('Thermostat edits must be a parameter mapping')
    parsed_edits = {}
    for name, value in edits.items():
        # Ordinary edits are already admitted by the owning settings planner.
        # Validate their scalar/schema domain here without importing that owner
        # (which composes this projection). This component never writes them.
        if (type(name) is not str or name == 'ApplicationNumber'
                or (name.startswith('Remote') and name not in REMOTE_EDIT_FIELDS[family])
                or (family == 'basic' and name in PROGRAM_FIELDS)):
            _fail('Setting is not admitted for ' + unit_type + ': ' + str(name))
        if name not in snapshot:
            _fail('Full thermostat snapshot lacks edited parameter: ' + name)
        parsed_edits[name] = _byte_parameter(spec, name, value)
    values = {}
    schema = {}
    for name in REMOTE_READ_FIELDS[family]:
        if name not in snapshot:
            _fail('Full thermostat snapshot lacks remote dependency: ' + name)
        values[name] = _byte_parameter(spec, name, snapshot[name])
        p = spec.get(name)
        schema[name] = {key: p.fields.get(key, default) for key, default in (
            ('Type', 'int'), ('Address', None), ('ArraySize', '1'), ('BitSize', '8'),
            ('BitAddress', '0'), ('ArraySkip', '0'))}
    values.update(parsed_edits)
    source = values['RemoteSetbackControlSource']
    if source > 2:
        _fail('RemoteSetbackControlSource must be 0..2; larger values leave unresolved save references')
    graph = snapshot_project(project_xml, unit_path)
    if dict(graph.unit_identity)['UnitType'] != unit_type:
        _fail('Project thermostat identity differs from the selected unit type')
    if not spec.supports_version(dict(graph.unit_identity)['FirmwareVersion']):
        _fail('Thermostat firmware is outside the decoded specification bounds')
    _, stored_unit = _selected_unit(_document(project_xml).documentElement, unit_path)
    for row in _children(stored_unit, 'PP'):
        name = row.getAttribute('Name')
        if name in REMOTE_READ_FIELDS[family]:
            if (not row.hasAttribute('Value')
                    or _byte_parameter(spec, name, row.getAttribute('Value'))
                    != _byte_parameter(spec, name, snapshot[name])):
                _fail('Stored project PP differs from the supplied remote snapshot: ' + name)
    schema = {'parameters': schema, 'spec_filename': spec.filename,
              'metadata': {key: spec.metadata.get(key, '') for key in ('Type', 'MinVersion', 'MaxVersion')}}
    apps = {app.address: app for app in graph.applications}
    live = {(app.address, group.address): group for app in graph.applications for group in app.groups}
    creations, getters = [], []

    def application(address, reason, enable_application):
        if address not in apps:
            if address != 203:
                _fail('Source 1 requires its selected ApplicationNumber application to exist')
            apps[address] = RemoteApplication(address, 'planned-application:203', 'Enable Control', (), '')
            creations.append(RemoteCreation('Application', 203, 203, 'Enable Control', reason))
            created = True
        else:
            created = False
        getters.append({'getter': 'GetEnableControlApplication' if enable_application else 'ApplicationObject',
                        'application': address, 'identity': apps[address].identity, 'created': created})
        return apps[address]

    def group(address, value, create, role, *, enable_application=True):
        app = application(address, role, enable_application)
        found = live.get((address, value))
        created = False
        if found is None and create:
            if sum(key[0] == address for key in live) >= 256:
                _fail('Remote group capacity prevents resolving ' + role)
            name = '<Unused>' if value == 255 else ('Enable Network Variable ' if address == 203 else 'Group ') + str(value)
            found = RemoteGroup(address, value, f'planned-group:{address}:{value}', name, 'Group', '')
            live[address, value] = found
            creations.append(RemoteCreation('Group', address, value, name, role))
            created = True
        getters.append({'getter': 'GroupByAddress', 'role': role, 'application': address,
                        'application_identity': app.identity, 'address': value, 'create': create,
                        'identity': found.identity if found else None, 'created': created})
        return found

    references = {}
    if source:
        app_address = 203 if source == 2 else values['ApplicationNumber']
        if source == 1 and not (48 <= app_address <= 95 or app_address == 203):
            _fail('Source 1 admits existing Lighting applications 48..95 or Enable Control 203')
        if source == 1 and app_address not in apps:
            _fail('Source 1 requires its selected ApplicationNumber application to exist')
        for name, role in zip(SETBACK_FIELDS[1:], ('setback_on', 'setback_off')):
            references[role] = group(app_address, values[name], True, role, enable_application=source == 2)
    else:
        references.update(setback_on=None, setback_off=None)
    expected = {name: values[name] for name in SETBACK_FIELDS}
    if source == 0:
        expected.update(RemoteSetbackOnGroup=30, RemoteSetbackOffGroup=31)
    enabled = False
    if family == 'programmable':
        evap = values['EvapProgramEnabled'] if values['EvapProgramEnabled'] <= 1 else 0
        nonevap = values['NonEvapProgramEnabled'] if values['NonEvapProgramEnabled'] <= 1 else 1
        enabled = bool(evap or nonevap)
        expected.update(EvapProgramEnabled=evap, NonEvapProgramEnabled=nonevap, RemoteScheduleEnable=int(enabled))
        for name, role, default in zip(SCHEDULE_GROUP_FIELDS, ('schedule_on', 'schedule_off', 'schedule_override'), (32, 33, 34)):
            references[role] = group(203, values[name] if enabled else 255, enabled, role)
            expected[name] = values[name] if enabled else default

    def unique(roles, label):
        selected = [references[role] for role in roles if references[role] is not None and references[role].address != 255]
        identities = [(row.application, row.identity) for row in selected]
        if len(identities) != len(set(identities)):
            _fail('Original remote validation rejects duplicate ' + label + ' group identities')

    unique(('setback_on', 'setback_off'), 'setback')
    if source and not any(references[role] is not None and references[role].address != 255
                          for role in ('setback_on', 'setback_off')):
        _fail('Original remote validation requires at least one non-unused setback group')
    if family == 'programmable':
        schedule = ('schedule_on', 'schedule_off', 'schedule_override')
        unique(schedule, 'schedule')
        if enabled and any(references[role] is None or references[role].address == 255 for role in schedule):
            _fail('Original enabled schedule validation rejects every unused or unresolved role')
        unique(schedule + ('setback_on', 'setback_off'), 'schedule/setback')
    roles = {name: None if value is None else {
        'application': value.application, 'address': value.address, 'identity': value.identity,
        'unused': value.address == 255} for name, value in references.items()}
    for name, value in expected.items():
        _byte_parameter(spec, name, value)
    validation = {'passed': True, 'setback_source': source, 'schedule_enabled': enabled,
        'duplicate_nonunused_identities_rejected': True, 'one_unused_setback_permitted': True,
        'enabled_schedule_unused_roles_rejected': family == 'programmable',
        'cross_role_identity_validation': family == 'programmable',
        'optional_missing_level_additions': 'declined', 'complete_parent_validation_reproduced': False}
    return RemoteReferencePlan(family, unit_type, tuple(sorted(snapshot.items())), tuple(sorted(parsed_edits.items())),
        project_xml, graph, tuple(sorted(expected.items())), tuple(creations), _json(getters), _json(roles),
        _json(validation), _json(schema))


def validate_remote_plan(store, plan):
    """Replay every bound input before the native owner starts mutations."""
    if type(plan) is not RemoteReferencePlan:
        _fail('Expected an issued thermostat remote reference plan')
    rebuilt = plan_remote_references(store, plan.unit_type, dict(plan.before), dict(plan.edits),
        project_xml=plan.project_xml, unit_path=plan.graph.unit_path)
    if rebuilt != plan:
        _fail('Thermostat remote plan differs from its complete deterministic replay')
    return plan


def _selected_unit(root, path):
    _, project_name, network_path, address = _unit_path(path)
    project = _children(root, 'Project')[0]
    if _field(project, 'Address').upper() != project_name.upper():
        _fail('Preservation project differs')
    network = _select(_address_rows(project, 'Network'), int(network_path.rsplit('/', 1)[1]), 'network')
    unit = _select(_address_rows(network, 'Unit'), address, 'unit')
    return network, unit


def _normalize_owned_pp(old_root, new_root, path, names):
    _, old_unit = _selected_unit(old_root, path)
    network, new_unit = _selected_unit(new_root, path)
    old = {row.getAttribute('Name'): row for row in _children(old_unit, 'PP') if row.hasAttribute('Name')}
    new = {row.getAttribute('Name'): row for row in _children(new_unit, 'PP') if row.hasAttribute('Name')}
    for name in names:
        before, after = old.get(name), new.get(name)
        if before is not None:
            if after is None or not after.hasAttribute('Value'):
                _fail('Owned stored PP parameter disappeared: ' + name)
            # Preserve every other attribute and child, including extensions.
            before.setAttribute('Value', '<owned-value>')
            after.setAttribute('Value', '<owned-value>')
        elif after is not None:
            attrs = {after.attributes.item(i).name for i in range(after.attributes.length)}
            if attrs != {'Name', 'Value'} or after.childNodes:
                _fail('Newly stored PP parameter has unplanned metadata: ' + name)
            new_unit.removeChild(after)
    return network


def verify_project_preservation(before_xml, after_xml, unit_path, *, changed_parameters, created_oids):
    """Compare the whole graph after removing exactly the admitted mutation set.

    ``created_oids`` maps (command kind, application, address) to returned OID.
    Group creates under 203 may serialize as Group or NetVar; retained kinds
    and all retained metadata remain exact. Changed PP readback belongs to the
    owning PP session; this helper preserves every other stored parameter.
    """
    try:
        before, after = snapshot_project(before_xml, unit_path), snapshot_project(after_xml, unit_path)
        if not isinstance(created_oids, Mapping) or not isinstance(changed_parameters, (Mapping, tuple, list, set, frozenset)):
            _fail('Preservation requires explicit changed parameter names and creation receipts')
        if any(type(name) is not str for name in changed_parameters):
            _fail('Changed parameter names must be text')
        names = set(changed_parameters)
        if len(set(created_oids.values())) != len(created_oids):
            _fail('Created object receipts contain duplicate OIDs')
        for key, oid in created_oids.items():
            if (type(key) is not tuple or len(key) != 3 or key[0] not in ('Application', 'Group')
                    or type(key[1]) is not int or type(key[2]) is not int):
                _fail('Malformed remote creation receipt key')
            _oid(oid)
            if oid in before.all_oids:
                _fail('Created object receipt reused an original OID')
        old_root, new_root = _document(before_xml).documentElement, _document(after_xml).documentElement
        network = _normalize_owned_pp(old_root, new_root, unit_path, names)
        applications = dict(_address_rows(network, 'Application'))
        rows, remove = [], []
        # Resolve and verify all receipts before removing parent applications.
        for (kind, application, address), oid in created_oids.items():
            if application not in applications:
                _fail('Created application is missing from readback')
            parent = applications[application]
            if kind == 'Application':
                if application != 203 or address != 203:
                    _fail('Unexpected application creation')
                node, name = parent, 'Enable Control'
            else:
                groups = [row for row in _children(parent) if row.tagName in ('Group', 'NetVar')
                          and not row.namespaceURI and _byte(_field(row, 'Address')) == address]
                if len(groups) != 1:
                    _fail('Created remote group is missing or duplicated')
                node = groups[0]
                if node.tagName == 'NetVar' and application != 203:
                    _fail('Unexpected native group serialization kind')
                name = '<Unused>' if address == 255 else ('Enable Network Variable ' if application == 203 else 'Group ') + str(address)
                if _children(node, 'Level'):
                    _fail('Reference-only transaction unexpectedly created remote levels')
            if _field(node, 'OID') != oid or _field(node, 'TagName') != name:
                _fail('Created remote object identity or name differs from its receipt')
            rows.append({'kind': kind, 'application': application, 'address': address, 'oid': oid,
                         'stored_kind': node.tagName})
            remove.append(node)
        removed_ids = {oid for oid in created_oids.values()}
        if set(after.all_oids) != set(before.all_oids) | removed_ids:
            _fail('Unexpected added or removed project object identities')
        # Parent removal must not conceal unplanned groups or levels.
        for (kind, app, _address), oid in created_oids.items():
            if kind == 'Application':
                parent = applications[app]
                descendants = _all_oids(parent)
                if set(descendants) - removed_ids:
                    _fail('Created application contains an unplanned child object')
        for node in reversed(remove):
            if node.parentNode is not None:
                node.parentNode.removeChild(node)
        unit_oid = dict(before.unit_identity)['OID']
        if _json(_canonical(old_root, unit_oid=unit_oid)) != _json(_canonical(new_root, unit_oid=unit_oid)):
            _fail('Unrelated project, unit, application, group or level metadata changed')
        return {'preserved': True, 'existing_metadata_preserved': True, 'unit_record_preserved': True,
                'unknown_project_data_preserved': True, 'created_objects': rows,
                'config_oid_normalization_ignored': True, 'empty_level_tags_dlt_normalization_ignored': True,
                'selected_unit_pp_collection_order_ignored': True}
    except ThermostatTemplateError:
        raise
    except (ValueError, KeyError, TypeError) as error:
        raise ThermostatTemplateError('Thermostat project preservation failed: ' + str(error)) from error
